"""Read-only, metadata-driven document identity evidence for query planning."""
from __future__ import annotations

from sqlalchemy import text
from ..data_catalog.physical import column_names, resolve_table_name
from .schema_loader import _load_schema_ai_config


def profile_document_identities(db, tables, columns, *, required_tables=()):
    rules = _load_schema_ai_config().get('document_identity_rules', {})
    profiles = {}
    monetary_tables = {c.split('.')[0].upper() for c in columns
                       if '.' in c and c.split('.')[-1].upper() in {'NETWR', 'WAVWR'}}
    monetary_tables.update(str(table).upper() for table in required_tables)
    for requested in tables:
        rule = rules.get(requested.upper())
        if not rule or requested.upper() not in monetary_tables:
            continue
        table = resolve_table_name(requested) or requested
        available = {c.upper(): c for c in column_names(table)}
        if not all(k in available for k in rule['keys']):
            continue
        keys = [available[k] for k in rule['keys']]
        chosen = {c.split('.', 1)[1].upper() for c in columns
                  if c.split('.', 1)[0].upper() == requested.upper() and '.' in c}
        attributes = [available[c] for c in sorted(chosen | set(rule.get('attributes', []))) if c in available]
        quote = lambda name: '"' + name.replace('"', '""') + '"'
        key_sql = ','.join(quote(k) for k in keys)
        value_sql = ','.join(quote(c) for c in attributes)
        if not value_sql:
            continue
        sql = f'''WITH duplicates AS (
            SELECT {key_sql}, COUNT(*) copies, COUNT(DISTINCT ROW({value_sql})) variants
            FROM {quote(table)} GROUP BY {key_sql} HAVING COUNT(*)>1)
            SELECT COUNT(*) duplicate_identity_groups, COALESCE(SUM(copies-1),0) extra_rows,
                   COUNT(*) FILTER (WHERE variants>1) conflicting_identity_groups FROM duplicates'''
        try:
            # A savepoint keeps a failed quality probe from poisoning the
            # investigation's database transaction.
            with db.begin_nested():
                row = dict(db.execute(text(sql)).mappings().one())
            profiles[table] = {'verified': True, 'keys': keys, 'checked_attributes': attributes,
                               **{k: int(v) for k, v in row.items()}}
        except Exception:
            profiles[table] = {'verified': False, 'keys': keys,
                               'limitation': 'Document identity uniqueness could not be verified.'}
    return profiles


def document_identity_errors(sql, profiles):
    """Require deduplication before aggregates over verified duplicate sources."""
    from sqlglot import exp, parse_one
    from sqlglot.optimizer.scope import Scope, build_scope

    duplicates = {t.upper(): p for t, p in profiles.items()
                  if p.get('verified') and p.get('duplicate_identity_groups', 0)}
    if not duplicates:
        return []
    try:
        tree = parse_one(sql, read='postgres')
        if not tree.find(exp.Sum) and not tree.find(exp.Avg):
            return []
        errors = []

        def visit(scope):
            select = scope.expression
            for alias, (_, source) in scope.selected_sources.items():
                if isinstance(source, Scope):
                    visit(source)
                elif isinstance(source, exp.Table) and source.name.upper() in duplicates:
                    profile = duplicates[source.name.upper()]
                    if profile.get('conflicting_identity_groups', 0):
                        errors.append(f'Data limitation: {source.name} has conflicting document identities; no verified version-selection rule is available.')
                        continue
                    projected = {c.name.upper() for p in select.expressions
                                 for c in [p.this if isinstance(p, exp.Alias) else p]
                                 if isinstance(c, exp.Column) and c.table == alias}
                    own_aggregate = any(n.find_ancestor(exp.Select) is select for n in select.find_all(exp.AggFunc))
                    group = select.args.get('group')
                    grouped = {c.name.upper() for c in (group.expressions if group else [])
                               if isinstance(c, exp.Column) and c.table == alias}
                    keys = {k.upper() for k in profile['keys']}
                    money_aggregate = any(isinstance(n, (exp.Sum, exp.Avg)) and n.find_ancestor(exp.Select) is select
                                          for n in select.find_all(exp.AggFunc))
                    row_distinct = select.args.get('distinct') and not own_aggregate and keys <= projected
                    row_group = group and not money_aggregate and keys <= projected and keys <= grouped
                    if not row_distinct and not row_group:
                        errors.append(f'{source.name} has verified duplicate document rows. Deduplicate identical rows with complete document keys and calculation attributes in a row SELECT DISTINCT before aggregation; never SUM(DISTINCT amount).')

        visit(build_scope(tree))
        return list(dict.fromkeys(errors))
    except Exception:
        return ['Document identity safety could not be established for duplicate-source aggregation.']
