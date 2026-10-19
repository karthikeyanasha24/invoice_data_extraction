"""Request-local relationship evidence, explicit plans and identified-value proofs.

Business names help discovery; only declared constraints or governed relationships
authorize joins. Imported key definitions are checked against this connection.
No model-supplied key or cardinality assertion is trusted.
"""
from __future__ import annotations

from collections import deque
import re
from dataclasses import dataclass, field
from typing import Any

from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import Scope, build_scope, traverse_scope


@dataclass
class RelationshipCatalog:
    schema: dict
    keys: dict[str, list[set[str]]] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)
    key_evidence: dict = field(default_factory=dict)

    def __post_init__(self):
        self.index = {t.lower(): t for t in self.schema}
        self.columns = {t: {c['col'].lower() for c in cols} for t, cols in self.schema.items()}
        self.column_names = {t: {c['col'].lower():c['col'] for c in cols} for t, cols in self.schema.items()}

    def table(self, name):
        if not isinstance(name, str) or name.lower() not in self.index:
            raise ValueError(f'Unknown source table: {name}')
        return self.index[name.lower()]

    def add_edge(self, left, right, pairs, provenance):
        left, right = self.table(left), self.table(right)
        pairs = [(a.lower(), b.lower()) for a, b in pairs]
        if not pairs or any(a not in self.columns[left] or b not in self.columns[right] for a, b in pairs):
            return
        if 'mandt' in self.columns[left] and 'mandt' in self.columns[right] and ('mandt', 'mandt') not in pairs:
            pairs.append(('mandt', 'mandt'))
        edge = dict(left=left, right=right, pairs=pairs, provenance=provenance)
        if edge not in self.edges:
            self.edges.append(edge)

    def paths(self, names):
        """BFS reaches previously unused intermediates; there is no two-hop limit."""
        names = [self.table(t) for t in names]
        paths = []
        for start, target in zip(names,names[1:]):
            queue = deque([(start, [], {start})])
            found = []
            shortest = None
            while queue:
                table, path, visited = queue.popleft()
                if shortest is not None and len(path)>shortest:
                    continue
                if table == target:
                    shortest = len(path)
                    found.append(path)
                    continue
                for edge in self.edges:
                    other = edge['right'] if edge['left'] == table else edge['left'] if edge['right'] == table else None
                    if other and other not in visited:
                        queue.append((other, path + [edge], visited | {other}))
                if len(queue)>1000:
                    raise ValueError('Too many relationship alternatives; specify intermediate tables')
            if not found:
                raise ValueError(f'No verified relationship path from {start} to {target}; inspect metadata or clarify the relationship')
            signatures = {tuple((e['left'],e['right'],tuple(e['pairs'])) for e in p):p for p in found}
            if len(signatures)>1:
                routes = [' -> '.join([start]+[f"{e['left']}/{e['right']}({e['pairs']})" for e in p]) for p in list(signatures.values())[:4]]
                raise ValueError('Ambiguous relationships. Specify the intended intermediate tables in path order or clarify the business role: '+'; '.join(routes))
            paths.append(next(iter(signatures.values())))
        return paths

    def inspect_keys(self, session, names):
        from sqlalchemy import inspect, text
        from .investigation_budget import checkpoint
        inspector = inspect(session.connection())
        # These are documented grains, not assumed DB constraints. All are
        # live-checked before entering a proof. Other tables use actual keys.
        imported_grains = {'VBRK': ['mandt', 'vbeln'], 'VBAK': ['mandt', 'vbeln'],
                           'VBRP': ['mandt', 'vbeln', 'posnr'], 'VBAP': ['mandt', 'vbeln', 'posnr'],
                           'KNA1': ['mandt', 'kunnr'], 'T016T': ['brsch']}
        for name in names:
            table = self.table(name)
            if table in self.key_evidence:
                continue
            checkpoint('RETRIEVING_SCHEMA')
            candidates = []
            pk = inspector.get_pk_constraint(table).get('constrained_columns') or []
            if pk:
                candidates.append(pk)
            candidates += [c['column_names'] for c in inspector.get_unique_constraints(table)]
            for index in inspector.get_indexes(table):
                if index.get('unique') and not index.get('dialect_options', {}).get('postgresql_where') and index.get('column_names') and all(index['column_names']):
                    candidates.append(index['column_names'])
            if not candidates and table.upper() in imported_grains:
                candidates.append(imported_grains[table.upper()])
            checked = []
            for candidate in candidates:
                columns = [c.lower() for c in candidate if isinstance(c, str)]
                if not columns or not set(columns) <= self.columns[table]:
                    continue
                quote = inspector.dialect.identifier_preparer.quote
                cols = ','.join(quote(self.column_names[table][c]) for c in columns)
                nulls = ' OR '.join(f'{quote(self.column_names[table][c])} IS NULL' for c in columns)
                # Metadata probes return one boolean, no business records.
                sql = f'SELECT EXISTS (SELECT 1 FROM {quote(table)} WHERE {nulls}) OR EXISTS (SELECT 1 FROM {quote(table)} GROUP BY {cols} HAVING COUNT(*)>1)'
                from .analyst_agent_sql import enforce_agent_user_scope
                scoped_sql, parameters = enforce_agent_user_scope(sql, self.schema)
                if not session.execute(text(scoped_sql), parameters).scalar():
                    checked.append(set(columns))
            self.keys[table] = checked
            self.key_evidence[table] = {'unique_keys': [sorted(k) for k in checked],
                                        'provenance': 'connected uniqueness/null check', 'request_local': True}
            for fk in inspector.get_foreign_keys(table):
                if (fk.get('referred_schema') in {None, inspector.default_schema_name}
                        and str(fk.get('referred_table')).lower() in self.index):
                    self.add_edge(table, fk['referred_table'], zip(fk['constrained_columns'], fk['referred_columns']), 'declared foreign key')
        for edge in self.edges:
            left = {a for a, _ in edge['pairs']}
            right = {b for _, b in edge['pairs']}
            a_unique = any(k <= left for k in self.keys.get(edge['left'], []))
            b_unique = any(k <= right for k in self.keys.get(edge['right'], []))
            edge['cardinality'] = '1:1' if a_unique and b_unique else 'N:1' if b_unique else '1:N' if a_unique else 'unknown'

    @classmethod
    def connected(cls, schema, session):
        from ..data_catalog.registry import RELATIONSHIPS
        catalog = cls(schema)
        grouped = {}
        for rel in RELATIONSHIPS:
            if not rel.get('usable_in_sql'):
                continue
            a, b = rel['source_table'].lower(), rel['target_table'].lower()
            if a in catalog.index and b in catalog.index:
                entry = grouped.setdefault((a, b), {'pairs': [], 'source': rel['source']})
                entry['pairs'].append((rel['source_column'], rel['target_column']))
        for (a, b), entry in grouped.items():
            # add_edge resolves physical table casing and adds MANDT when
            # present on both sources. Registry names need not match DB case.
            catalog.add_edge(a, b, entry['pairs'], entry['source'])
        # Discover all declared FKs in one catalog read, including intermediate
        # tables not yet mentioned by the model. Constraints contain no records.
        from sqlalchemy import text
        if session.get_bind().dialect.name == 'postgresql':
            rows = session.execute(text("""SELECT c.conname, a.relname AS source_table,b.relname AS target_table,
                sa.attname AS source_column,ta.attname AS target_column,k.ordinality
                FROM pg_constraint c JOIN pg_class a ON a.oid=c.conrelid JOIN pg_class b ON b.oid=c.confrelid
                JOIN pg_namespace n ON n.oid=a.relnamespace JOIN pg_namespace nb ON nb.oid=b.relnamespace
                CROSS JOIN LATERAL unnest(c.conkey,c.confkey) WITH ORDINALITY AS k(s,t,ordinality)
                JOIN pg_attribute sa ON sa.attrelid=a.oid AND sa.attnum=k.s
                JOIN pg_attribute ta ON ta.attrelid=b.oid AND ta.attnum=k.t
                WHERE c.contype='f' AND n.nspname=current_schema() AND nb.nspname=current_schema()
                ORDER BY c.conname,k.ordinality""")).mappings()
            groups = {}
            for row in rows:
                if row['source_table'].lower() in catalog.index and row['target_table'].lower() in catalog.index:
                    groups.setdefault((row['source_table'], row['target_table'], row['conname']), []).append((row['source_column'], row['target_column']))
            for (a, b, constraint), pairs in groups.items():
                catalog.add_edge(a, b, pairs, f'declared foreign key {constraint}')
        return catalog


def requested_sources(question, schema):
    """Source coverage comes from the request and governed business names."""
    from ..data_catalog.registry import get_table_entry
    found = set()
    q = question.lower().replace('-', ' ')
    for table in schema:
        if re.search(r'\b' + re.escape(table.lower()) + r'\b', q):
            found.add(table)
        entry = get_table_entry(table) or {}
        names = [str(entry.get('business_name') or '').lower()] + entry.get('aliases', [])
        # Header and item descriptions can share terms; use the exact documented
        # entity name and allow ordinary plurals, not fuzzy field equality.
        if any(name and re.search(r'\b' + re.escape(name) + r's?\b', q) for name in names):
            found.add(table)
    return found


def output_lineage(sql):
    """Resolve output fields to physical origins through arbitrary CTE names."""
    root = build_scope(parse_one(sql, read='postgres'))
    def describe(scope):
        sources = {a: describe(src) if isinstance(src, Scope) else None for a, (_, src) in scope.selected_sources.items()}
        outputs = {}
        for p in scope.expression.selects:
            refs = set()
            for c in p.find_all(exp.Column):
                if c.table not in sources:
                    continue
                if sources[c.table] is None:
                    refs.add((scope.selected_sources[c.table][1].name, c.name.lower()))
                else:
                    refs.update(sources[c.table].get(c.name.lower(), set()))
            outputs[p.alias_or_name.lower()] = refs
        return outputs
    return describe(root)


def source_coverage_issues(question, sql, schema):
    required = requested_sources(question, schema)
    if len(required) < 2:
        return []
    lineage = output_lineage(sql)
    origins = {t.lower() for refs in lineage.values() for t, _ in refs}
    missing = sorted(t for t in required if t.lower() not in origins)
    issues = ['Requested sources do not contribute output fields: ' + ', '.join(missing)] if missing else []
    if re.search(r'net\s+(?:sales|values?|amount)|side by side', question, re.I):
        for table in required:
            cols = {c['col'].lower() for c in schema[table]}
            if 'netwr' in cols and not any((table, 'netwr') in refs for refs in lineage.values()):
                issues.append(f'Requested net value from {table}.netwr is missing from output')
    return issues


def validate_plan(plan, question, catalog):
    if not isinstance(plan.get('fields'), list) or not isinstance(plan.get('tables'), list) or not isinstance(plan.get('grain'), str) or type(plan.get('limit')) is not int:
        raise ValueError('Malformed analysis plan')
    tables = [catalog.table(t) for t in plan['tables']]
    if not tables or not plan['fields'] or not plan['grain'].strip():
        raise ValueError('Plan needs source tables, output fields and an explicit grain')
    if not set(requested_sources(question, catalog.schema)) <= set(tables):
        raise ValueError('Plan omits a source explicitly required by the user')
    if plan['limit'] < 1 or plan['limit'] > 200:
        raise ValueError('Plan row limit must be 1–200')
    for predicate in plan.get('filters',[]):
        if isinstance(predicate,str):
            continue  # persisted v2 plans; SQL checker permits only supported legacy predicates
        if not isinstance(predicate,dict) or set(predicate)!={'table','column','operator','values'}:
            raise ValueError('Use typed table/column/operator/values filters')
        table = catalog.table(predicate['table'])
        if predicate['column'].lower() not in catalog.columns[table] or table not in tables:
            raise ValueError('Filter must reference a planned physical field')
        if predicate['operator'] not in {'eq','neq','in','gte','gt','lte','lt','year','is_null','not_null'} or not isinstance(predicate['values'],list) or not all(isinstance(v,str) for v in predicate['values']):
            raise ValueError('Invalid typed filter operator or values')
        predicate['table'] = table
    aliases = set()
    for f in plan['fields']:
        if not isinstance(f, dict) or f.get('role') not in {'identifier','measure','currency','dimension','date'} or not isinstance(f.get('column'), str) or not isinstance(f.get('alias'), str):
            raise ValueError('Malformed plan field')
        t = catalog.table(f['table'])
        if t not in tables or f['column'].lower() not in catalog.columns[t]:
            raise ValueError('Plan field does not exist on a planned source')
        f['table'] = t
        if not f['alias'] or f['alias'].lower() in aliases:
            raise ValueError('Every planned field needs a distinct output alias')
        aliases.add(f['alias'].lower())
    if re.search(r'net\s+(?:sales|values?|amount)|side by side', question, re.I):
        for table in requested_sources(question, catalog.schema):
            if 'netwr' in catalog.columns[table] and not any(f['table'] == table and f['column'].lower() == 'netwr' and f['role'] == 'measure' for f in plan['fields']):
                raise ValueError(f'Plan omits the requested net value from {table}')
    measured = {f['table'] for f in plan['fields'] if f['role'] == 'measure'}
    if len(measured) > 1:
        for table in measured:
            fields = {f['column'].lower() for f in plan['fields'] if f['table'] == table}
            if plan.get('strategy', 'identified_values') == 'identified_values' and not any(key <= fields | {'mandt'} for key in catalog.keys.get(table, [])):
                raise ValueError(f'Comparison plan must expose the verified identity of {table}')
            if 'waerk' in catalog.columns[table] and not any(f['table'] == table and f['column'].lower() == 'waerk' and f['role'] == 'currency' for f in plan['fields']):
                raise ValueError(f'Comparison plan must expose the currency of {table}; do not assume currencies match')
        if any('mandt' in catalog.columns[t] for t in measured) and not any(f['column'].lower() == 'mandt' for f in plan['fields']):
            raise ValueError('Comparison plan must expose the SAP client')
    if any(s['alias'].lower() not in aliases for s in plan['sort']):
        raise ValueError('Sort field must name a planned output')
    plan['tables'] = tables
    plan['relationships'] = catalog.paths(tables)
    plan['key_evidence'] = {t: catalog.key_evidence.get(t, {}) for t in tables}
    plan['validated'] = True
    return plan


def plan_sql_issues(sql, plan):
    lineage = output_lineage(sql)
    from .analyst_filters import filter_issues
    issues = filter_issues(sql,plan.get('filters',[]))
    for f in plan['fields']:
        if (f['table'], f['column'].lower()) not in lineage.get(f['alias'].lower(), set()):
            issues.append(f"Missing planned output {f['alias']} from {f['table']}.{f['column']}")
    root = parse_one(sql, read='postgres')
    if not root.args.get('limit') or not isinstance(root.args['limit'].expression, exp.Literal) or int(root.args['limit'].expression.this) > plan['limit']:
        issues.append('SQL row bound exceeds the validated plan limit')
    order = root.args.get('order')
    for i, expected in enumerate(plan['sort']):
        node = order.expressions[i] if order and i < len(order.expressions) else None
        if node is None or node.this.alias_or_name.lower() != expected['alias'].lower() or bool(node.args.get('desc')) != (expected['direction'] == 'DESC'):
            issues.append('SQL sort does not match the validated plan')
    return issues


def failed_sql_signature(sql):
    """Ignore whitespace, comments, alias and CTE renames in repeated failures."""
    tree = parse_one(sql, read='postgres')
    aliases = {}
    for node in tree.find_all(exp.CTE):
        aliases.setdefault(node.alias, f'cte_{len(aliases)}')
    for node in tree.find_all(exp.TableAlias):
        aliases.setdefault(node.name, f'alias_{len(aliases)}')
    for node in tree.find_all(exp.TableAlias):
        node.set('this', exp.to_identifier(aliases[node.name]))
    for node in tree.find_all(exp.Table):
        if node.name in aliases:
            node.set('this', exp.to_identifier(aliases[node.name]))
    for node in tree.find_all(exp.Column):
        if node.table in aliases:
            node.set('table', exp.to_identifier(aliases[node.table]))
    return tree.sql(normalize=True, comments=False)


def prior_cohort(context, question, catalog):
    """Recover bounded identifiers for explicit extensions, never for new topics."""
    if not re.search(r'\b(?:those|these|them|same|compare now)\b', question, re.I) or not re.search(r'\b(?:compare|linked|related|industry|add|include)\b', question, re.I):
        return None
    if re.search(r'\b(?:instead|overall|all documents)\b', question, re.I):
        return None
    plan = context.get('previousPlan') or {}
    retained = plan.get('retained_analytical_context') if isinstance(plan, dict) else None
    if not context.get('previousSQL') and isinstance(retained, dict):
        context = retained
    if not str(context.get('previousAnswerStatus', '')).startswith('SUCCESS'):
        return None
    rows = context.get('data') or []
    if not rows or len(rows) > 200:
        return None
    previous = output_lineage(context.get('previousSQL') or '')
    scope = build_scope(parse_one(context.get('previousSQL') or '', read='postgres'))
    def base_table(s):
        source = next(iter(s.selected_sources.values()))[1]
        return base_table(source) if isinstance(source, Scope) else source.name
    primary = base_table(scope)
    # Enrichment preserves the original result's base document cohort, even
    # when every linked document also has a populated ID in the prior result.
    for table, keys in sorted(catalog.keys.items(), key=lambda item:item[0] != primary):
        if table != primary:
            continue
        for key in keys:
            aliases = {c: next((name for name, refs in previous.items() if (table, c) in refs), None) for c in key}
            if not all(aliases.values()):
                continue
            values = [{c: row.get(a) for c, a in aliases.items()} for row in rows]
            if all(all(v is not None for v in value.values()) for value in values):
                return {'table': table, 'keys': sorted(key), 'values': list({json_key(v): v for v in values}.values()),
                        'meaning': 'previous displayed document cohort, re-read under current authorization'}
    return None


def json_key(value):
    import json
    return json.dumps(value, sort_keys=True, default=str)


def constrain_cohort(sql, cohort):
    if not cohort:
        return sql
    tree = parse_one(sql, read='postgres')
    applied = False
    for scope in traverse_scope(tree):
        for alias, (_, source) in scope.selected_sources.items():
            if not isinstance(source, exp.Table) or source.name != cohort['table']:
                continue
            choices = [exp.and_(*[exp.EQ(this=exp.column(k, table=alias), expression=exp.convert(v[k])) for k in cohort['keys']]) for v in cohort['values']]
            scope.expression.where(exp.or_(*choices), append=True, copy=False)
            applied = True
    if not applied:
        raise ValueError('Follow-up must re-read the previously selected document source, not switch to an unrelated cohort')
    return tree.sql(dialect='postgres')


def identified_value_proof(sql, catalog, measure_fields=None, *, allow_currency_matched_difference=False):
    """Prove a non-additive row listing's complete identity and verified joins.

    DISTINCT link projections define a pair grain. Monetary facts are never
    aggregated in this proof. Equality closure proves every composite link and
    output identity, including bridges and arbitrarily deep CTEs. Fail closed.
    """
    money = {'netwr', 'wavwr'} | {c.lower() for _, c in (measure_fields or [])}
    tree = parse_one(sql, read='postgres')
    root = build_scope(tree)
    errors = []

    def describe(scope):
        select = scope.expression
        aggregate_nodes = [n for n in select.find_all(exp.AggFunc) if n.find_ancestor(exp.Select) is select]
        if not isinstance(select, exp.Select) or (aggregate_nodes and (len(scope.selected_sources) != 1 or select.args.get('joins'))):
            raise ValueError('Listing proof cannot aggregate independent values; aggregate each fact separately before joining')
        for window in select.find_all(exp.Window):
            if window.find_ancestor(exp.Select) is select and type(window.this).__name__ not in {'RowNumber', 'Rank', 'DenseRank'}:
                raise ValueError('Unproven measure window over joined facts')
        infos = {}
        for alias, (_, source) in scope.selected_sources.items():
            if isinstance(source, Scope):
                infos[alias] = describe(source)
            else:
                table = catalog.table(source.name)
                keys = catalog.keys.get(table, [])
                infos[alias] = ({c: {(table, c)} for c in catalog.columns[table]}, [set(k) for k in keys], set())
        refs = {}
        projected = set()
        measures = set()
        measured_aliases = set()
        for p in select.selects:
            value = p.this if isinstance(p, exp.Alias) else p
            columns = [c for c in value.find_all(exp.Column) if c.table in infos]
            origins = set().union(*(infos[c.table][0].get(c.name.lower(), set()) for c in columns)) if columns else set()
            refs[p.alias_or_name.lower()] = origins
            if isinstance(value, exp.Column):
                projected.add((value.table, value.name.lower()))
            if any(c in money for _, c in origins):
                measures.update(t for t, c in origins if c in money)
                measured_aliases.update(c.table for c in columns if any(name in money for _, name in infos[c.table][0].get(c.name.lower(), set())))
                measure_tables = {t for t, c in origins if c in money}
                if len(measure_tables) > 1:
                    def source_tables(node):
                        return {table for column in node.find_all(exp.Column) if column.table in infos
                                for table, name in infos[column.table][0].get(column.name.lower(), set())
                                if name in money}

                    compatible_difference = False
                    if allow_currency_matched_difference and isinstance(value, exp.Sub):
                        left_sources, right_sources = source_tables(value.this), source_tables(value.expression)
                        if len(left_sources) == 1 and len(right_sources) == 1 and left_sources != right_sources:
                            currency_outputs = {table for output_origins in refs.values() for table, name in output_origins
                                                if re.search(r'(?:currency|waerk|waers)', name, re.I)}
                            exposes_both_currencies = (left_sources | right_sources) <= currency_outputs
                            for equality in select.find_all(exp.EQ):
                                if equality.find_ancestor(exp.Select) is not select:
                                    continue
                                left, right = equality.this, equality.expression
                                if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                                    continue
                                left_name, right_name = left.name.lower(), right.name.lower()
                                if not (re.search(r'(?:currency|waerk|waers)', left_name)
                                        and re.search(r'(?:currency|waerk|waers)', right_name)):
                                    continue
                                left_origins = infos.get(left.table, ({}, [], set()))[0].get(left_name, set())
                                right_origins = infos.get(right.table, ({}, [], set()))[0].get(right_name, set())
                                if exposes_both_currencies and (any(a in left_sources and b in right_sources for a, _ in left_origins for b, _ in right_origins) or any(
                                        b in left_sources and a in right_sources for a, _ in left_origins for b, _ in right_origins)):
                                    compatible_difference = True
                                    break
                    if not compatible_difference:
                        raise ValueError('Compare independently sourced values side by side; calculate a difference only when both currencies are explicitly matched and displayed')
        parent = {}
        def find(x):
            parent.setdefault(x, x)
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        def union(a, b):
            parent[find(a)] = find(b)
        seen = set()
        base = next(iter(infos), None)
        if base:
            seen.add(base)
        for join in select.args.get('joins') or []:
            target = join.this.alias_or_name
            on = join.args.get('on')
            if on is None or on.find(exp.Or) or join.args.get('side') in {'RIGHT', 'FULL'}:
                raise ValueError('Listing requires explicit verified AND joins; RIGHT/FULL joins need a separate grain proof')
            pairs = []
            def atoms(n):
                if isinstance(n, exp.Paren):
                    return atoms(n.this)
                if isinstance(n, exp.And):
                    return atoms(n.this) + atoms(n.expression)
                return [n]
            for atom in atoms(on):
                if isinstance(atom, exp.EQ) and isinstance(atom.this, exp.Column) and isinstance(atom.expression, exp.Column):
                    a, b = atom.this, atom.expression
                    if {a.table, b.table} <= set(infos) and target in {a.table, b.table} and ({a.table, b.table} - {target}) <= seen:
                        x, y = (a.table, a.name.lower()), (b.table, b.name.lower())
                        pairs.append((x, y))
                        union(x, y)
            physical_pairs = set()
            for (a, ac), (b, bc) in pairs:
                for left in infos[a][0].get(ac, set()):
                    for right in infos[b][0].get(bc, set()):
                        physical_pairs.add((left, right))
                        physical_pairs.add((right, left))
            valid_edges = []
            for edge in catalog.edges:
                needed = {((edge['left'], a), (edge['right'], b)) for a, b in edge['pairs']}
                if needed <= physical_pairs:
                    valid_edges.append(needed)
            permitted = set().union(*valid_edges) if valid_edges else set()
            permitted |= {(b, a) for a, b in permitted}
            # Equality on the same physical origin reconnects a scoped CTE to its
            # fact, e.g. a ranked cohort, without inventing a business relation.
            same_origins = {p for p in physical_pairs if p[0] == p[1]}
            approved = permitted | same_origins
            if not physical_pairs or not all(any((left, right) in approved
                    for left in infos[a][0].get(ac, set()) for right in infos[b][0].get(bc, set()))
                    for (a, ac), (b, bc) in pairs):
                raise ValueError('Join lacks a verified relationship or complete composite keys; use find_relationships and retain every key (including client)')
            if join.args.get('side') == 'LEFT':
                for (a, ac), (b, bc) in pairs:
                    left = (a, ac) if a != target else (b, bc)
                    # A nullable right-side ID cannot stand in for an earlier
                    # bridge key: two absent targets could otherwise collapse
                    # into indistinguishable NULL pairs.
                    if any(left[1] in key for key in infos[left[0]][1]) and not any(
                            p[0] in seen and find(p) == find(left) for p in projected):
                        raise ValueError(f'Preserve the left-side link reference {left[0]}.{left[1]} in output; '
                                         'a missing target ID cannot identify an unmatched document pair. '
                                         'Project this bridge column with its own alias as well as the target document ID')
            seen.add(target)
        # A projected composite-key component can carry equivalent origins from
        # earlier verified joins. This is necessary for multi-hop bridge CTEs.
        for p in select.selects:
            value = p.this if isinstance(p, exp.Alias) else p
            if isinstance(value, exp.Column) and value.table in infos:
                key = find((value.table, value.name.lower()))
                for alias, (fields, _, _) in infos.items():
                    for column, origins in fields.items():
                        if find((alias, column)) == key:
                            refs[p.alias_or_name.lower()].update(origins)
        exposed = {find(p) for p in projected}
        all_keys = set()
        if aggregate_nodes:
            if any(info[2] for info in infos.values()):
                raise ValueError('Do not re-sum already aggregated facts')
            if any(not infos[a][1] for a in measured_aliases):
                raise ValueError('Verify the source fact identity before aggregating its values')
            groups = (select.args.get('group').expressions if select.args.get('group') else [])
            output_keys = set()
            for group in groups:
                matching = next((p.alias_or_name.lower() for p in select.selects if (p.this if isinstance(p, exp.Alias) else p) == group), None)
                if matching is None:
                    raise ValueError('Project every aggregation key before joining independent facts')
                output_keys.add(matching)
            return refs, [output_keys], measures
        for alias, (_, keys, _) in infos.items():
            candidate = next((k for k in keys if {find((alias, c)) for c in k} <= exposed), None)
            if candidate is None and (alias in measured_aliases or not select.args.get('distinct')):
                raise ValueError('Unproven row grain: deduplicate the non-monetary link to the full document pair, retain fact identifiers and display values without SUM')
            if candidate:
                all_keys.update((alias, c) for c in candidate)
        for table in measures:
            if any(table in info[2] for info in infos.values()):
                continue
            keys = catalog.keys.get(table, [])
            def visible(column):
                return any(find((a, c)) in exposed for a, (fields, _, _) in infos.items()
                           for c, origins in fields.items() if (table, column) in origins)
            if not any(all(visible(c) for c in k) for k in keys):
                raise ValueError(f'Monetary source {table} must expose its complete verified identity')
        if select.args.get('distinct'):
            keys = [set(refs)]
        else:
            output_keys = {p.alias_or_name.lower() for p in select.selects
                           if isinstance(p.this if isinstance(p, exp.Alias) else p, exp.Column)
                           and find(((p.this if isinstance(p, exp.Alias) else p).table,
                                     (p.this if isinstance(p, exp.Alias) else p).name.lower())) in {find(k) for k in all_keys}}
            keys = [output_keys] if output_keys else []
        return refs, keys, set().union(*(info[2] for info in infos.values()))
    try:
        refs, _, _ = describe(root)
        if not any(c in money for origins in refs.values() for _, c in origins):
            raise ValueError('No identified monetary output')
    except (ValueError, KeyError, AttributeError, StopIteration) as error:
        errors.append(str(error))
    return not errors, errors
