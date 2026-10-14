"""Curated database questions exercised by verify_basic_catalog.py.

Verification concerns query execution and result shape on the tested extract;
it is not a guarantee that another deployment has the same data or permissions.
"""

DATABASE_QUESTIONS = (
    ("Customers", "top 5 customers by billed sales in 2000"),
    ("Customers", "bottom 5 customers by billed sales in 2000"),
    ("Customers", "top 5 customers by billed sales in 2002"),
    ("Customers", "top 5 customers by billed sales in 1999"),
    ("Customers", "bottom 5 customers by billed sales in 1999"),
    ("Customers", "top 5 customers by invoice count in 2001"),
    ("Customers", "bottom 5 customers by invoice count in 2001"),
    ("Customers", "top 5 customers by billed quantity in 2001"),
    ("Customers", "billed sales by customer in 2000"),
    ("Customers", "billed sales by customer in 2002"),
    ("Countries", "top 5 countries by billed sales in 2000"),
    ("Countries", "bottom 5 countries by billed sales in 2000"),
    ("Countries", "top 5 countries by billed sales in 2002"),
    ("Countries", "top 5 countries by billed sales in 2003"),
    ("Countries", "top 5 countries by billed quantity in 2001"),
    ("Countries", "billed sales by country in 2000"),
    ("Countries", "billed sales by country in 2002"),
    ("Countries", "billed sales for Germany in 2000"),
    ("Industries", "top 5 industries by billed sales in 2000"),
    ("Industries", "bottom 5 industries by billed sales in 2000"),
    ("Industries", "top 5 industries by billed sales in 2002"),
    ("Industries", "top 5 industries by billed quantity in 2001"),
    ("Industries", "billed sales by industry in 2001"),
    ("Industries", "billed sales by industry in 2002"),
    ("Materials", "top 5 materials by billed sales in 2000"),
    ("Materials", "bottom 5 materials by billed sales in 2000"),
    ("Materials", "top 5 materials by billed sales in 2002"),
    ("Materials", "billed sales by material in 2001"),
    ("Materials", "billed sales by material in 2002"),
    ("Billing documents", "top 5 billing documents by billed sales in 2000"),
    ("Billing documents", "bottom 5 billing documents by billed sales in 2000"),
    ("Billing documents", "top 5 billing documents by billed sales in 2001"),
    ("Billing documents", "bottom 5 billing documents by billed sales in 2001"),
    ("Customers", "top 5 customers by billed sales in 2003"),
    ("Customers", "bottom 5 customers by billed sales in 2002"),
    ("Document counts", "how many sales orders are there"),
    ("Document counts", "how many billing documents are there"),
    ("Document counts", "how many sales orders in 2000"),
    ("Document counts", "how many sales orders in 2001"),
    ("Document counts", "how many billing documents in 1999"),
    ("Document counts", "how many billing documents in 2000"),
    ("Document counts", "how many billing documents in 2002"),
    ("Document counts", "how many billing documents in 2000 and 2001"),
    ("Customers", "billed sales by customer in 1999"),
    ("Sales trends", "billed sales by month in 2000"),
    ("Countries", "top 5 countries by billed sales in 1999"),
    ("Sales trends", "billed sales by month in 2002"),
    ("Countries", "billed sales for Germany in 2002"),
    ("Master data", "list customers in France"),
    ("Order coverage", "customers with no billing in 2000"),
)


def database_question_suggestions():
    return [{"category": category, "question": question} for category, question in DATABASE_QUESTIONS]
