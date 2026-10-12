"""Typed plan predicates must be entailed by conjunctive executed SQL filters."""
from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import Scope, traverse_scope

FILTER_SCHEMA = {'type':'array','items':{'type':'object','additionalProperties':False,
    'properties':{'table':{'type':'string'},'column':{'type':'string'},
        'operator':{'type':'string','enum':['eq','neq','in','gte','gt','lte','lt','year','is_null','not_null']},
        'values':{'type':'array','items':{'type':'string'}}},
    'required':['table','column','operator','values']}}


def filter_issues(sql, filters):
    from .agent_query_contract import output_lineage
    from .plan_satisfaction import sql_has_calendar_year
    scopes = list(traverse_scope(parse_one(sql,read='postgres')))
    errors = []
    def refs(scope,node):
        found = set()
        for col in node.find_all(exp.Column):
            source = scope.sources.get(col.table)
            if isinstance(source,exp.Table):
                found.add((source.name.lower(),col.name.lower()))
            elif isinstance(source,Scope):
                found.update((t.lower(),c.lower()) for t,c in output_lineage(source.expression.sql(dialect='postgres')).get(col.name.lower(),set()))
        return found
    def terms(node):
        if isinstance(node,exp.Paren):
            return terms(node.this)
        if isinstance(node,exp.And):
            return terms(node.this)+terms(node.expression)
        return [] if isinstance(node,exp.Or) else [node]
    for rule in filters or []:
        if isinstance(rule,str):
            # Older persisted plans are not silently treated as typed proof.
            import re
            year = re.fullmatch(r'(?:billing )?year (\d{4})',rule.strip(),re.I)
            if year and sql_has_calendar_year(sql,int(year.group(1))):
                continue
            errors.append('Rebuild the legacy text filter as a typed predicate: '+rule)
            continue
        target = (rule['table'].lower(),rule['column'].lower())
        candidates = [(scope,p) for scope in scopes if scope.expression.args.get('where')
                      for p in terms(scope.expression.args['where'].this) if refs(scope,p)=={target}]
        # Explicit nested loops avoid accessing a missing WHERE in a comprehension.
        values = rule['values']; op = rule['operator']; matched = False
        if op=='year':
            for scope,_ in candidates:
                predicates = [p.copy() for s,p in candidates if s is scope]
                narrowed = exp.select('*').from_('period_source').where(exp.and_(*predicates)).sql(dialect='postgres')
                if len(values)==1 and values[0].isdigit() and sql_has_calendar_year(narrowed,int(values[0])):
                    matched = True
        else:
            classes = {'eq':exp.EQ,'neq':exp.NEQ,'gte':exp.GTE,'gt':exp.GT,'lte':exp.LTE,'lt':exp.LT}
            for scope,predicate in candidates:
                p = predicate
                if op in {'is_null','not_null'}:
                    if op=='not_null' and isinstance(p,exp.Not):
                        p=p.this
                    elif op=='not_null':
                        continue
                    matched |= isinstance(p,exp.Is) and isinstance(p.expression,exp.Null)
                elif op=='in' and isinstance(p,exp.In):
                    matched |= all(isinstance(v,exp.Literal) for v in p.expressions) and set(v.this for v in p.expressions)==set(values)
                elif op in classes and isinstance(p,classes[op]) and len(values)==1:
                    value = p.expression
                    matched |= bool(isinstance(value,exp.Literal) and value.this==values[0] and refs(scope,p.this)=={target}
                        and not any(isinstance(n,(exp.Add,exp.Sub,exp.Mul,exp.Div)) for n in p.this.walk()))
        if not matched:
            errors.append(f"Missing required filter {rule['table']}.{rule['column']} {op} {values}")
    return errors
