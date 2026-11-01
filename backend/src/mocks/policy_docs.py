"""Synthetic policy documents served by the Policy Knowledge system.

Clause ids are what the policy engine cites; the text is what the customer sees in the sources footer.
"""

CLAUSES = [
    {"clause_id": "LOAN-TNC-4.1", "doc": "Personal Loan Terms", "section": "Interest",
     "text": "Interest is computed monthly on the reducing outstanding principal. The monthly rate is the "
             "annual rate divided by twelve. EMIs are rounded to the nearest rupee; the final EMI is adjusted "
             "for rounding."},
    {"clause_id": "LOAN-TNC-4.3", "doc": "Personal Loan Terms", "section": "Floating rate reset",
     "text": "For Flexi (floating rate) loans the rate is the External Benchmark Lending Rate (EBLR) plus a spread "
             "fixed at sanction. When the EBLR changes, the loan rate is reset on the first day of the next calendar "
             "quarter. The remaining tenure stays the same and the EMI is recalculated on the outstanding principal. "
             "Customers are notified by SMS and email at least 30 days before the new EMI applies."},
    {"clause_id": "LOAN-TNC-4.4", "doc": "Personal Loan Terms", "section": "Fixed rate",
     "text": "For Fixed rate loans the rate agreed at sanction applies for the full tenure and the EMI does not "
             "change except after a part-prepayment."},
    {"clause_id": "LOAN-TNC-7.2", "doc": "Personal Loan Terms", "section": "Prepayment, floating rate",
     "text": "No prepayment or foreclosure charges apply to floating rate loans availed by individuals. "
             "Part-prepayments of any amount of at least Rs 5,000 are allowed at any time. The customer chooses "
             "whether to reduce the tenure or the EMI."},
    {"clause_id": "LOAN-TNC-7.4", "doc": "Personal Loan Terms", "section": "Lock-in, fixed rate",
     "text": "Fixed rate loans have a lock-in period of 12 months from the date of disbursal. Part-prepayment and "
             "foreclosure are not permitted during the lock-in period."},
    {"clause_id": "LOAN-TNC-7.5", "doc": "Personal Loan Terms", "section": "Prepayment, fixed rate",
     "text": "After the lock-in period, part-prepayments of at least Rs 10,000 are permitted up to two times in a "
             "financial year. A prepayment charge of 3% of the amount prepaid plus applicable GST (18%) applies."},
    {"clause_id": "LOAN-TNC-8.1", "doc": "Personal Loan Terms", "section": "Foreclosure",
     "text": "A loan may be foreclosed by paying the outstanding principal, interest accrued since the last EMI "
             "date and applicable charges. Floating rate loans: no charge. Fixed rate loans: permitted after the "
             "12-month lock-in with a charge of 3% of the outstanding principal plus GST."},
    {"clause_id": "LOAN-TNC-9.2", "doc": "Personal Loan Terms", "section": "Dishonour charges",
     "text": "If an EMI debit is dishonoured, a charge of Rs 500 plus GST (Rs 590 in total) is levied once per "
             "dishonoured instalment. The debit may be re-presented within 7 days."},
    {"clause_id": "LOAN-TNC-9.4", "doc": "Personal Loan Terms", "section": "Disputes",
     "text": "Customers may dispute any charge within 90 days of the date it was levied. Charges levied in error "
             "are reversed within 7 working days of the dispute being accepted."},
    {"clause_id": "LOAN-TNC-10.1", "doc": "Personal Loan Terms", "section": "Statements",
     "text": "A repayment statement can be requested at any time through any channel at no charge and is "
             "issued within one working day."},
    {"clause_id": "LOAN-TNC-11.2", "doc": "Personal Loan Terms", "section": "Repayment mandate",
     "text": "EMIs are collected through a NACH or UPI AutoPay mandate. An expired mandate must be renewed; until "
             "then EMIs can be paid through UPI or net banking before the due date."},
    {"clause_id": "CARD-TNC-3.1", "doc": "Credit Card Terms", "section": "Billing cycle",
     "text": "The billing cycle runs from the 16th of a month to the 15th of the next. The statement is generated on "
             "the 15th and payment is due 20 days after the statement date."},
    {"clause_id": "CARD-TNC-3.4", "doc": "Credit Card Terms", "section": "Minimum amount due",
     "text": "The minimum amount due is 5% of the statement balance excluding EMI instalments (at least Rs 200), "
             "plus all EMI instalments, fees and taxes billed in the statement."},
    {"clause_id": "CARD-TNC-4.2", "doc": "Credit Card Terms", "section": "Interest-free period",
     "text": "Purchases enjoy an interest-free period of 20 to 50 days from the purchase date to the payment due "
             "date, provided the previous statement was paid in full."},
    {"clause_id": "CARD-TNC-5.1", "doc": "Credit Card Terms", "section": "EMI conversion",
     "text": "Purchases of Rs 2,500 or more can be converted to EMIs of 3 to 24 months. A one-time processing fee of "
             "Rs 199 plus GST applies. Each instalment is billed in the monthly statement."},
    {"clause_id": "CARD-TNC-6.2", "doc": "Credit Card Terms", "section": "Disputed transactions",
     "text": "A transaction can be disputed within 60 days of the statement date on which it first appeared. The "
             "disputed amount is excluded from the minimum amount due while the dispute is investigated, and a "
             "decision is communicated within 30 days."},
]
