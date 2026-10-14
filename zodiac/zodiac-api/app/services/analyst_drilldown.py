"""Authorized immutable results and deterministic aggregate-to-document queries.

No language model participates. Unsupported SQL shapes fail explicitly. The
original aggregate and a live detail snapshot are distinct pieces of evidence.
"""
from __future__ import annotations
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import Scope, build_scope
from sqlalchemy import Table, Column, String, Integer, Text, MetaData, select, insert
from sqlalchemy.orm import Session

metadata = MetaData()
artifacts = Table('ai_analyst_results', metadata,
    Column('id', String(64), primary_key=True), Column('user_id', Integer, nullable=False, index=True),
    Column('created_at', String(40), nullable=False), Column('expires_at', String(40), nullable=False),
    Column('scope_digest', String(64), nullable=False), Column('payload', Text, nullable=False))


def scope_digest(scope):
    if scope is None or scope.user_id <= 0:
        raise PermissionError('Authenticated result owner is required')
    return hashlib.sha256(json.dumps({'user':scope.user_id,'access':scope.sap_access,
        'dataset_version':os.getenv('AI_ANALYST_DATASET_VERSION','unversioned'),
        'pairs':sorted(scope.allowed_sap_pairs,key=lambda p:(p['client'],p['customer'])),
        'customers':sorted(scope.allowed_customer_ids)},sort_keys=True).encode()).hexdigest()


def store_artifact(engine, scope, payload):
    # Separate short transaction: analytical sessions may be read-only.
    metadata.create_all(engine, tables=[artifacts])
    now = datetime.now(timezone.utc)
    identifier = uuid.uuid4().hex
    with Session(engine) as session:
        session.execute(insert(artifacts).values(id=identifier, user_id=scope.user_id,
            created_at=now.isoformat(), expires_at=(now+timedelta(days=7)).isoformat(),
            scope_digest=scope_digest(scope), payload=json.dumps(payload,default=str)))
        session.commit()
    return identifier


def load_artifact(engine, scope, identifier):
    if not isinstance(identifier,str) or not __import__('re').fullmatch(r'[0-9a-f]{32}',identifier):
        raise ValueError('Invalid result reference')
    with Session(engine) as session:
        row = session.execute(select(artifacts).where(artifacts.c.id==identifier,
            artifacts.c.user_id==scope.user_id)).mappings().first()
    if not row or row['scope_digest'] != scope_digest(scope):
        raise PermissionError('Result is unavailable for the current permissions')
    if datetime.fromisoformat(row['expires_at']) < datetime.now(timezone.utc):
        raise ValueError('Result expired; run the analysis again')
    return json.loads(row['payload'])


def _unalias(node):
    return node.this if isinstance(node,exp.Alias) else node


def _resolve(scope, node, target=None):
    node = _unalias(node)
    if scope is target:
        return scope, node
    if isinstance(node,exp.Column) and node.table in scope.sources and isinstance(scope.sources[node.table],Scope):
        child = scope.sources[node.table]
        output = next((p for p in child.expression.selects if p.alias_or_name.lower()==node.name.lower()),None)
        if output is not None:
            return _resolve(child,output,target)
    return scope,node


FREEZE_LIMIT = 5000


def _output_expression(scope, name):
    return next((p for p in scope.expression.selects if p.alias_or_name.lower() == name.lower()), None)


def _expand(scope, node):
    """Replace subquery outputs with the expression that defines them."""
    node = _unalias(node)
    if isinstance(node, exp.Column):
        source = scope.sources.get(node.table) if node.table else None
        if isinstance(source, Scope):
            output = _output_expression(source, node.name)
            if output is None:
                raise ValueError('A selected amount uses a column that is not in its source query')
            return _expand(source, output)
        return scope, node.copy()
    if isinstance(node, (exp.Literal, exp.Null, exp.Boolean)):
        return None, node.copy()
    clone = node.copy()
    base = None
    for column in list(clone.find_all(exp.Column)):
        child, replacement = _expand(scope, column)
        if child is not None:
            if base is not None and base is not child:
                raise ValueError('This amount combines billing documents from more than one query block')
            base = child
        column.replace(replacement)
    return base, clone


def _lineage_scopes(scope, node):
    pending = [(scope, node)]
    found = []
    seen = set()
    while pending:
        current, expression = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        found.append(current)
        for column in _unalias(expression).find_all(exp.Column):
            source = current.sources.get(column.table) if column.table else None
            if isinstance(source, Scope):
                output = _output_expression(source, column.name)
                if output is not None:
                    pending.append((source, _unalias(output)))
    return found


def _conjuncts(node):
    if node is None:
        return []
    if isinstance(node, (exp.Where, exp.Paren)):
        return _conjuncts(node.this)
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


def _signed_terms(node, sign=1):
    node = _unalias(node)
    if isinstance(node, exp.Paren):
        return _signed_terms(node.this, sign)
    if isinstance(node, exp.Neg):
        return _signed_terms(node.this, -sign)
    if isinstance(node, exp.Sub):
        return _signed_terms(node.this, sign) + _signed_terms(node.expression, -sign)
    if isinstance(node, exp.Add):
        return _signed_terms(node.this, sign) + _signed_terms(node.expression, sign)
    if isinstance(node, exp.Sum):
        if isinstance(node.this, exp.Distinct) or node.find_ancestor(exp.Window):
            raise ValueError('Only additive SUM measures have invoice drill-down; ratios, averages and forecasts require their own explanation')
        return [(sign, node.this)]
    raise ValueError('Only additive SUM measures have invoice drill-down; ratios, averages and forecasts require their own explanation')


def _summed_money_columns(node):
    """Money columns inside a sum. Date tests in a CASE choose rows; they are not the amount."""
    node = _unalias(node)
    if isinstance(node, (exp.Cast, exp.Paren)):
        return _summed_money_columns(node.this)
    if isinstance(node, exp.Case):
        columns = []
        for branch in node.args.get('ifs') or []:
            columns.extend(_summed_money_columns(branch.args.get('true')))
        default = node.args.get('default')
        if default is not None and not (isinstance(default, exp.Literal) and default.is_number):
            columns.extend(_summed_money_columns(default))
        return columns
    if isinstance(node, exp.Column):
        return [node]
    if isinstance(node, exp.Literal):
        return []
    return [column for column in node.find_all(exp.Column)]


def compile_selection(sql, row, measure, schema):
    from .analyst_agent_sql import validate_agent_sql
    sql, _ = validate_agent_sql(sql,schema)
    root = parse_one(sql,read='postgres')
    if not isinstance(root,exp.Select):
        raise ValueError('This result needs an explicit document analysis; set operations cannot be drilled automatically')
    top = build_scope(root)
    projection = next((p for p in root.selects if p.alias_or_name==measure),None)
    if projection is None:
        raise ValueError('Select a returned monetary measure')
    scope,total = _resolve(top,projection)
    terms = _signed_terms(total)
    parts = []
    base = None
    monetary_columns = []
    for sign, argument in terms:
        base_scope, expression = _expand(scope, argument)
        if base_scope is None:
            raise ValueError('This measure has no billing source')
        if base is not None and base is not base_scope:
            raise ValueError('Independent source measures require separate drill-downs')
        base = base_scope
        monetary_columns.extend(_summed_money_columns(expression))
        parts.append(expression if sign == 1 else exp.Neg(this=expression))
    if not monetary_columns or any(c.name.lower()!='netwr' for c in monetary_columns):
        raise ValueError('This measure is not a documented billed-net contribution')
    aliases = {c.table for c in monetary_columns}
    if len(aliases)!=1:
        raise ValueError('Independent source measures require separate drill-downs')
    alias = next(iter(aliases))
    source = base.sources.get(alias)
    if not isinstance(source,exp.Table) or source.name.upper() not in {'VBRK','VBRP'}:
        raise ValueError('The selected amount is not a directly traceable billing measure')
    for ancestor in _lineage_scopes(scope, total):
        if ancestor is not scope and ancestor.expression.args.get('group'):
            raise ValueError('This total is summed from an already aggregated query, so its invoices cannot be listed without double counting')
    columns = {c['col'].lower():c['col'] for t,cols in schema.items() if t.lower()==source.name.lower() for c in cols}
    keys = ['mandt','vbeln'] + (['posnr'] if source.name.upper()=='VBRP' else [])
    if not set(keys)<=set(columns):
        raise ValueError('Complete billing identity is required for reconciliation')
    def field(name):
        return exp.column(columns[name],table=alias,quoted=True)
    contribution = parts[0]
    for part in parts[1:]:
        contribution = exp.Add(this=contribution, expression=part)
    detail = base.expression.copy()
    predicates = []
    dimensions = {}
    currency = None
    for grouping in (scope.expression.args.get('group') or exp.Group()).expressions:
        # Resolve GROUP BY output aliases and ordinal references explicitly.
        group = grouping
        if isinstance(group,exp.Literal) and group.is_int:
            group = _unalias(scope.expression.selects[int(group.this)-1])
        elif isinstance(group,exp.Column) and not group.table:
            projected = next((p for p in scope.expression.selects if p.alias_or_name==group.name),None)
            if projected is not None:
                group = _unalias(projected)
        match = None
        for output in root.selects:
            owner,expression = _resolve(top,output,scope)
            if owner is scope and expression.sql(normalize=True)==group.sql(normalize=True):
                match = output.alias_or_name
                break
        if match is None or match not in row:
            raise ValueError('A hidden grouping field prevents an exact selection; include every grouping dimension')
        value = row[match]
        dimensions[match] = value
        predicates.append(exp.Is(this=group.copy(),expression=exp.Null()) if value is None else exp.EQ(this=group.copy(),expression=exp.convert(value)))
        if any(c.name.lower() in {'waerk','waers','currency'} for c in group.find_all(exp.Column)):
            currency = group.copy()
    currency_filters = []
    for ancestor in _lineage_scopes(scope, total):
        currency_filters.extend(_conjuncts(ancestor.expression.args.get('where')))
    if currency is None:
        currency = field('waerk') if 'waerk' in columns else None
        if currency is None or not any(isinstance(p,exp.EQ) and
                any(c.name.lower() in {'waerk','waers','currency'} for c in p.find_all(exp.Column)) and
                any(isinstance(v,exp.Literal) and v.is_string for v in p.iter_expressions())
                for p in currency_filters):
            raise ValueError('Group or explicitly filter billing currency before drilling into a monetary total')
    else:
        _, currency = _expand(scope, currency)
    expressions = [exp.alias_(field('mandt'),'sap_client',quoted=True),exp.alias_(field('vbeln'),'billing_document',quoted=True),
        exp.alias_(currency,'currency',quoted=True),exp.alias_(contribution,'contribution',quoted=True)]
    if 'posnr' in keys:
        expressions.append(exp.alias_(field('posnr'),'billing_item',quoted=True))
    detail.set('expressions',expressions)
    for name in ('group','having','order','qualify'):
        detail.set(name,None)
    if base is scope:
        detail.set('limit',None)
        detail.set('offset',None)
    detail.set('distinct',exp.Distinct())
    for predicate in predicates:
        _, left = _expand(scope, predicate.this)
        detail.where(exp.Is(this=left, expression=exp.Null()) if isinstance(predicate, exp.Is) else exp.EQ(this=left, expression=predicate.expression.copy()), append=True, copy=False)
    if base is not scope:
        for ancestor in _lineage_scopes(scope, total):
            if ancestor is base:
                continue
            for piece in _conjuncts(ancestor.expression.args.get('where')):
                _, expanded = _expand(ancestor, piece)
                detail.where(expanded, append=True, copy=False)
    # Retain only upstream CTE dependencies, not the original ranking/aggregate.
    original_with = root.args.get('with_')
    if original_with:
        needed = {t.name for t in detail.find_all(exp.Table)}
        kept = []
        for cte in reversed(original_with.expressions):
            if cte.alias in needed:
                kept.insert(0,cte.copy())
                needed.update(t.name for t in cte.find_all(exp.Table))
        detail.set('with_',exp.With(expressions=kept) if kept else None)
    details = f'''SELECT sap_client,billing_document,currency,SUM(contribution) AS billed_sales
        FROM ({detail.sql(dialect='postgres')}) AS contributions
        GROUP BY sap_client,billing_document,currency
        HAVING SUM(contribution) <> 0'''
    return {'details_sql':details,'dimensions':dimensions,'measure':measure,'expected_total':str(row[measure]),
        'metric':'billed net value' if len(terms)==1 else 'difference of billed net values', 'metric_version':'billing_net_v1',
        'grain':'billing document within SAP client and currency', 'source_table':source.name}


def drilldown_note(sql, rows, schema):
    """Why a verified result cannot be opened into billing documents, if it cannot."""
    if len(rows) == 1 and isinstance(rows[0], dict) and set(rows[0]) in (
        {"billing_document_count"}, {"sales_order_count"},
    ):
        return None
    if choices(sql, rows, schema):
        return None
    reasons = []
    try:
        root = parse_one(sql, read='postgres')
        row = rows[0] if rows else {}
        for projection in root.selects:
            try:
                compile_selection(sql, row, projection.alias_or_name, schema)
            except ValueError as exc:
                reasons.append(str(exc))
            except (KeyError, AttributeError, TypeError, IndexError):
                continue
    except Exception:
        reasons = []
    if any('currency' in reason.lower() for reason in reasons):
        return 'This total mixes billing currencies, so it cannot be opened as one invoice list. Ask again for one currency, for example total billed sales in 2001 in DEM.'
    return 'This result has no billed-net total that can be opened into billing documents. A ratio, average, or balance that is not a sum of invoice net value needs its own explanation.'


def choices(sql, rows, schema):
    if not rows:
        return []
    root = parse_one(sql,read='postgres')
    result = []
    for projection in root.selects:
        alias = projection.alias_or_name
        try:
            compile_selection(sql, rows[0], alias, schema)
            result.append(alias)
        except (ValueError, KeyError, AttributeError, TypeError, IndexError):
            continue
    return result


def capture_result(payload, engine, scope, schema):
    """Persist source evidence once; the browser carries only an opaque reference."""
    if not str(payload.get('answer_status','')).startswith('SUCCESS') or not payload.get('sql') or not payload.get('data'):
        return
    primary = next((r for r in payload.get('agent_results',[]) if r.get('id')==payload.get('agent_primary_result_id')), {})
    query = primary.get('unscoped_sql') or payload['sql']
    available = choices(query,payload['data'],schema)
    now = datetime.now(timezone.utc).isoformat()
    if not available:
        payload.setdefault('meta',{})['drilldown_unavailable'] = drilldown_note(query, payload['data'], schema)
        return
    artifact = {'kind':'query_result','sql':query,'displayed_sql':payload['sql'],'rows':payload['data'],
        'source':primary.get('source','business'), 'schema':schema,
        'question':(payload.get('query_plan') or {}).get('effective_question',''),
        'measures':available,'created_at':now,'metric_version':'billing_net_v1',
        'source_freshness':'Extract refresh time unavailable; this is query execution time',
        'truncated':bool((payload.get('meta') or {}).get('result_truncated'))}
    identifier = store_artifact(engine,scope,artifact)
    reference = {'id':identifier,'measures':available,'created_at':now,'expires_in_days':7,
        'source':artifact['source'],'metric_version':artifact['metric_version'],'source_freshness':artifact['source_freshness']}
    payload.setdefault('query_plan',{})['result_reference'] = reference
    payload.setdefault('meta',{})['result_reference'] = reference


def _document_followup(question):
    import re
    if not re.search(r'\b(?:invoices?|billing\s+docs?|billing\s+documents?)\b', question, re.I):
        return False
    if re.search(r'\b(?:customers?|countries|country|products?|materials?|vendors?|sold-to|payer|regions?|company)\b', question, re.I):
        return False
    if re.search(r'\b(?:related|contribut|behind|those|these|this|that|displayed|current|above|previous|same)\b', question, re.I):
        return True
    return bool(re.search(r'\b(?:show|list|find|open|display)\b', question, re.I))


def select_row(artifact, question):
    """Conservative typed follow-up resolution; ambiguous rows must be selected."""
    import re
    if not _document_followup(question):
        return None
    if not artifact.get('measures'):
        return 'unavailable'
    candidates = list(enumerate(artifact['rows']))
    years = re.findall(r'\b(?:19|20)\d{2}\b',question)
    currencies = [code for code in re.findall(r'\b[A-Z]{3}\b',question)
                  if code not in {'SAP', 'SQL', 'ERP', 'VAT', 'EDI', 'API'}]
    if years:
        dated = [(i,r) for i,r in candidates if any(str(r[k]) in years for k in r if re.search('year',k,re.I))]
        if dated:
            candidates = dated
        elif any(any(re.search('year', k, re.I) for k in r) for _, r in candidates):
            return 'scope_mismatch'
    if currencies:
        candidates = [(i,r) for i,r in candidates if any(str(r[k]) in currencies for k in r if re.search('currency|waerk|waers',k,re.I))]
        if not candidates:
            return 'scope_mismatch'
    measures = artifact.get('measures') or []
    named = [name for name in measures if years and any(year in str(name) for year in years)]
    if years and not named:
        measure_years = re.findall(r'\b(?:19|20)\d{2}\b', ' '.join(str(m).replace('_', ' ') for m in measures))
        context_years = re.findall(r'\b(?:19|20)\d{2}\b', str(artifact.get('question') or ''))
        known_years = measure_years or context_years
        if known_years and not set(years).intersection(known_years):
            return 'scope_mismatch'
    measure = named[0] if len(named)==1 else (measures[0] if len(measures)==1 else None)
    if re.search(r'\b(?:amount|value|total|sales|behind|line)\b', question, re.I):
        numbers = [n for n in re.findall(r'(?<![\w])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![\w])', question)
                   if n not in years]
        if numbers:
            matching = []
            for i, row in candidates:
                for name in ([measure] if measure else measures):
                    try:
                        amount = Decimal(str(row[name]).replace(',', ''))
                        for number in numbers:
                            raw = number.replace(',', '')
                            precision = len(raw.rsplit('.', 1)[-1]) if '.' in raw else 0
                            if abs(amount - Decimal(raw)) <= Decimal(5).scaleb(-precision - 1):
                                matching.append((i, name))
                                break
                    except (KeyError, ArithmeticError, ValueError):
                        continue
            matching = list(dict.fromkeys(matching))
            if len(matching) == 1:
                return matching[0]
            return 'ambiguous' if matching else 'scope_mismatch'
    if measure and len(candidates)==1:
        return candidates[0][0], measure
    return 'ambiguous'


def page_sql(selection, after=None, page_size=50):
    if not 1<=page_size<=100:
        raise ValueError('Page size must be 1–100')
    where = ''
    if after is not None:
        if not isinstance(after,list) or len(after)!=3 or not all(isinstance(v,str) and len(v)<=200 for v in after):
            raise ValueError('Invalid page cursor')
        literals = ','.join(exp.Literal.string(v).sql(dialect='postgres') for v in after)
        where = f'WHERE (sap_client,currency,billing_document) > ({literals})'
    return f'''WITH detail AS ({selection['details_sql']}),
        totals AS (SELECT COUNT(*) AS total_documents, SUM(billed_sales) AS reconciled_total,
          COUNT(DISTINCT currency) AS currency_count,
          MD5(STRING_AGG(CONCAT_WS('|',sap_client,currency,billing_document,billed_sales),'|' ORDER BY sap_client,currency,billing_document)) AS snapshot_digest FROM detail),
        page AS (SELECT * FROM detail {where} ORDER BY sap_client,currency,billing_document LIMIT {page_size+1})
        SELECT t.total_documents,t.reconciled_total,t.currency_count,t.snapshot_digest,p.*
        FROM totals t LEFT JOIN page p ON TRUE ORDER BY p.sap_client,p.currency,p.billing_document LIMIT {page_size+1}'''


def list_sql(selection, limit=FREEZE_LIMIT):
    if not 1 <= limit <= FREEZE_LIMIT:
        raise ValueError('The saved document list is limited to 5000 billing documents')
    return f'''SELECT sap_client,billing_document,currency,billed_sales
        FROM ({selection['details_sql']}) AS listed
        ORDER BY sap_client,currency,billing_document
        LIMIT {limit + 1}'''


def document_digest(documents):
    payload = '|'.join(f"{d['sap_client']}|{d['currency']}|{d['billing_document']}|{d['billed_sales']}" for d in documents)
    return hashlib.sha256(payload.encode()).hexdigest()


def frozen_page(selection, documents, page_size, after=None, frozen_at=None, source_executed_at=None):
    if not 1 <= page_size <= 100:
        raise ValueError('Page size must be 1–100')
    ordered = sorted(documents, key=lambda row: (str(row['sap_client']), str(row['currency']), str(row['billing_document'])))
    digest = document_digest(ordered)
    if after is not None:
        if not isinstance(after, list) or len(after) != 3:
            raise ValueError('Invalid page cursor')
        key = tuple(after)
        ordered = [row for row in ordered if (str(row['sap_client']), str(row['currency']), str(row['billing_document'])) > key]
    page = ordered[:page_size]
    total = sum((Decimal(str(row['billed_sales'])) for row in documents), Decimal('0'))
    currencies = {str(row['currency']) for row in documents}
    expected = Decimal(selection['expected_total'])
    difference = total - expected
    matched = difference == 0 and len(currencies) <= 1
    when = frozen_at or datetime.now(timezone.utc).isoformat()
    return {'answer_status':'SUCCESS' if matched else 'RECONCILIATION_MISMATCH',
        'data':page,'rowCount':len(page),'totalCount':len(documents),
        'has_more':len(ordered) > page_size,
        'next_cursor':[page[-1][k] for k in ('sap_client','currency','billing_document')] if len(ordered) > page_size else None,
        'reconciliation':{'original_total':format(expected,'f'),'document_total':format(total,'f'),
            'difference':format(difference,'f'),'matched':matched,'currency_count':len(currencies),
            'snapshot_digest':digest,'frozen':True,'frozen_at':when,
            'source_executed_at':source_executed_at,
            'original_snapshot_recreated':False,
            'note':f'These billing documents were saved at {when}, from the result captured at {source_executed_at or "the original query"}. Later pages read that saved copy, so a later change in the extract does not alter this list. The copy expires with the saved result.'},
        'selection':{k:v for k,v in selection.items() if k!='details_sql'},
        'llm_calls':0, 'meta':{'deterministic':True,'model_tokens':0,'metric_version':'billing_net_v1'}}


def reconcile(selection, rows, page_size, expected_digest=None):
    if not rows:
        raise ValueError('Reconciliation returned no evidence')
    summary = rows[0]
    digest = summary['snapshot_digest']
    if expected_digest is not None and digest!=expected_digest:
        raise ValueError('The contributing documents changed between pages; restart this drill-down')
    expected = Decimal(selection['expected_total'])
    actual = Decimal(str(summary['reconciled_total'] or '0'))
    difference = actual-expected
    documents = [{k:r[k] for k in ('sap_client','billing_document','currency','billed_sales')} for r in rows if r.get('billing_document') is not None]
    page = documents[:page_size]
    return {'answer_status':'SUCCESS' if difference==0 and int(summary['currency_count'])<=1 else 'RECONCILIATION_MISMATCH',
        'data':page,'rowCount':len(page),'totalCount':int(summary['total_documents']),
        'has_more':len(documents)>page_size,
        'next_cursor':[page[-1][k] for k in ('sap_client','currency','billing_document')] if len(documents)>page_size else None,
        'reconciliation':{'original_total':format(expected,'f'),'document_total':format(actual,'f'),
            'difference':format(difference,'f'),'matched':difference==0 and int(summary['currency_count'])<=1,
            'currency_count':int(summary['currency_count']), 'snapshot_digest':digest,
            'original_snapshot_recreated':False,
            'note':'Current contributing documents were read in one database statement. The original result total is preserved; historical source membership was not frozen.'},
        'selection':{k:v for k,v in selection.items() if k!='details_sql'},
        'llm_calls':0, 'meta':{'deterministic':True,'model_tokens':0,'metric_version':'billing_net_v1'}}
