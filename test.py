print("hello")
from query import get
print(get("18")["dr"].fillna(0).sum())
from query import get
df = get("18")
df[df["dr"].fillna(0) > 0].drop_duplicates(["bill_no", "dr"])["dr"].sum() 
print("distinct debits:", )