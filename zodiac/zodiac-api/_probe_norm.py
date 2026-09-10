from app.services.ranking_question_normalizer import normalize_ranking_question
q = "Which country had the highest sales growth and which customers contributed most to that growth?"
print(normalize_ranking_question(q))
q2 = "Which customers generated the highest billed sales?"
print(normalize_ranking_question(q2))
