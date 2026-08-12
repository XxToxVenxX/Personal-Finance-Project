# Expense Category Taxonomy

This is the single source of truth for categorization. Every transaction resolves
to exactly one `category` + `subcategory` pair from this list. Nothing outside
this list may be created at runtime.

If a transaction does not fit, assign `Uncategorized > Needs Review` and surface
it in the review list at the end of the run.

---

## 1. Food & Dining

| Subcategory | Covers |
|---|---|
| Groceries | Supermarkets, kirana, monthly provisions, BigBasket, DMart |
| Food Delivery | Swiggy, Zomato, restaurant delivery |
| Dining Out | Restaurant bills paid in person, POS at a venue |
| Cafes & Beverages | Coffee shops, tea, juice bars, bakery walk-ins |
| Quick Commerce | Zepto, Blinkit, Instamart — 10-minute delivery apps |

## 2. Transport

| Subcategory | Covers |
|---|---|
| Fuel | Petrol, diesel, EV charging |
| Ride Hailing | Uber, Ola, Rapido, autos paid via UPI |
| Public Transport | Metro, bus passes, local trains (commute, not intercity travel) |
| Vehicle Maintenance | Servicing, spares, tyres, vehicle insurance, PUC |
| Parking & Tolls | FASTag recharges, parking fees |

## 3. Housing & Utilities

| Subcategory | Covers |
|---|---|
| Rent | Monthly rent, brokerage, security deposit |
| Electricity | MSEDCL and other DISCOM bills |
| Water & Gas | Piped gas, LPG cylinders, water charges |
| Internet & Broadband | Home internet |
| Mobile & DTH | Prepaid/postpaid recharges, DTH |
| Society & Maintenance | Society charges, repairs, domestic help |

## 4. Shopping

| Subcategory | Covers |
|---|---|
| Clothing & Footwear | Apparel, shoes, accessories |
| Electronics & Gadgets | Phones, laptops, peripherals, appliances |
| Home & Furniture | Furniture, kitchenware, decor, hardware |
| Personal Care Products | Toiletries, cosmetics, skincare |
| General Marketplace | Amazon/Flipkart orders whose contents are unknown |

## 5. Health & Wellness

| Subcategory | Covers |
|---|---|
| Pharmacy | Medicines, PharmEasy, Apollo, 1mg |
| Doctor & Diagnostics | Consultations, lab tests, scans, dental |
| Hospital & Procedures | Admissions, surgeries |
| Fitness | Gym membership, sports club, yoga, trek training fees |

## 6. Entertainment & Subscriptions

| Subcategory | Covers |
|---|---|
| Streaming & OTT | Netflix, Prime, Spotify, JioHotstar |
| Software & Cloud | Claude, GitHub, domains, hosting, dev tools |
| Events & Movies | Cinema, concerts, BookMyShow |
| Gaming & Hobbies | Games, hobby equipment, hobby supplies |

## 7. Travel

| Subcategory | Covers |
|---|---|
| Flights | Airfare, seat/baggage add-ons |
| Trains & Buses | IRCTC, intercity bus, intercity cabs |
| Accommodation | Hotels, hostels, teahouses, Airbnb |
| Trek & Outdoor | Permits, guides, porters, gear rental, trek operators |
| Trip Miscellaneous | Visa fees, forex markup on a trip, travel insurance |

## 8. Financial

| Subcategory | Covers |
|---|---|
| Investments | SIP debits, lump-sum MF purchases, stock/ETF buys, PPF, NPS |
| Insurance Premiums | Life, health, term (not vehicle — that is Vehicle Maintenance) |
| Loan Repayment | EMI where the loan is a genuine liability outflow |
| Bank Charges & Fees | Annual fees, late fees, SMS charges, ATM fees, forex markup |
| Interest Paid | Credit card revolving interest, loan interest component |
| Taxes | Advance tax, self-assessment tax, professional tax |

## 9. Education & Career

| Subcategory | Covers |
|---|---|
| Courses & Certifications | Online courses, certification exam fees |
| Books & Materials | Books, study material |
| Applications & Exams | Application fees, language tests, credential evaluation |

## 10. Personal & Family

| Subcategory | Covers |
|---|---|
| Gifts | Gifts given, wedding cash gifts |
| Family Support | Money sent to family as support |
| Donations | Charity, religious donations |
| Grooming | Salon, barber, spa |

## 11. Income

Positive-signed rows. Excluded from expense totals; reported separately.

| Subcategory | Covers |
|---|---|
| Salary | Monthly salary credit |
| Reimbursements | Employer expense reimbursements |
| Interest & Dividends | Savings interest, FD interest, dividends |
| Refunds | Merchant refunds, cancelled order reversals |
| Cashback & Rewards | Credit card cashback, statement credits |

## 12. Transfers

Excluded from both income and expense totals. These are internal money movement,
not consumption. Getting this wrong double-counts spending.

| Subcategory | Covers |
|---|---|
| Credit Card Payment | Bank debit that settles the credit card bill |
| Self Transfer | Between own accounts, to/from own wallets |
| Wallet Load | Paytm/PhonePe/Amazon Pay top-ups |
| ATM Withdrawal | Cash withdrawal — the spend is invisible, do not classify it |
| Investment Redemption | MF/stock sale proceeds returning to the bank |

## 13. Uncategorized

| Subcategory | Covers |
|---|---|
| Needs Review | Unmatched merchant, unparseable narration, ambiguous case |

---

## Boundary Rules

These are the cases that cause drift between months. Apply them literally.

1. **Quick Commerce vs Groceries.** Zepto, Blinkit, and Instamart always go to
   `Food & Dining > Quick Commerce`, regardless of what was bought. DMart,
   BigBasket, and physical supermarkets always go to `Groceries`.
2. **Swiggy/Zomato.** Always `Food Delivery`. Do not attempt to split out
   Instamart orders based on narration — the bank narration rarely distinguishes
   them reliably.
3. **Amazon and Flipkart.** Default to `Shopping > General Marketplace` unless
   the narration explicitly names a product line. Do not infer contents from the
   amount.
4. **Vehicle insurance** is `Transport > Vehicle Maintenance`. Health, life, and
   term insurance are `Financial > Insurance Premiums`.
5. **Credit card bill payment** is always `Transfers > Credit Card Payment` on
   the bank side, and must be matched against the card statement so the
   underlying purchases are counted once, on the card side only.
6. **ATM withdrawals** are `Transfers > ATM Withdrawal`, never an expense. Cash
   spending is out of scope for this pipeline.
7. **SIP debits** are `Financial > Investments`, not transfers. They are an
   outflow from the spending pool even though the money is still yours. Report
   them in a separate savings-rate block, not in the discretionary spend total.
8. **Commute vs Travel.** Anything within the home city is `Transport`. Anything
   intercity or overnight is `Travel`.
9. **Fitness for a trek** is `Health & Wellness > Fitness`. Gear and permits for
   the trek itself are `Travel > Trek & Outdoor`.
10. **Forex markup** on a foreign transaction is `Financial > Bank Charges &
    Fees` when it appears as a separate line, even if the purchase itself is a
    trip expense.
11. **Refunds** are `Income > Refunds` and reduce the net monthly figure. Do not
    negate the original expense row — leave the history intact.
12. **A UPI transfer to a person** with no other signal goes to
    `Uncategorized > Needs Review`. Do not guess between Family Support, Gifts,
    and a split bill.

---

## Merchant Mapping

Confirmed merchant-to-category decisions are stored in the merchant map cache.
The cache is authoritative: if a merchant is present, use it and do not re-ask
an LLM. Only genuinely unseen merchant strings are sent for classification.

When I correct a categorization, update the cache entry so the correction holds
for all future months.
