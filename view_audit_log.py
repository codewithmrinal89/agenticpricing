"""Print the audit log as a readable table."""
from agents.audit_log import read_log

records = read_log()

if not records:
    print("Audit log is empty -- run a pricing request first (e.g. python -m agents.supervisor <part_number>).")
else:
    print(f"{'Timestamp':<26} {'Part Number':<18} {'Decision':<30} {'Price':>10} {'Flags':>6}")
    for r in records:
        print(
            f"{r['timestamp']:<26} {r['part_number']:<18} {r['decision']:<30} "
            f"{r['recommended_price']:>10.2f} {len(r['flags']):>6}"
        )
    print(f"\n{len(records)} decision(s) logged.")
