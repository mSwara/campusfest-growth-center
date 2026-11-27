"""Scenario model for the NEXT edition, calibrated on the 2025 final actuals in the supplied data.

For each campaign c with spend S (INR):
    identified = I0 * (min(S/S0, cap) ** beta)        diminishing returns, capped by channel capacity
    registered = identified * reg_rate (+ reg uplift)
    attended   = registered * show_rate (+ show uplift, max 95%)
    + unattributed walk-ins (held at the 2025 level)

I0, S0, reg_rate and show_rate are measured from the data (final snapshot). beta and cap are ASSUMPTIONS
(documented in the README) because the data has one spend level per campaign, so elasticity cannot be estimated.
"""
import analytics as A

BETA = {"C01": 0.80, "C02": 0.60, "C03": 0.60, "C04": 0.80, "C05": 0.85, "C06": 0.50, "C07": 0.80}
CAP = {"C01": 2.0, "C02": 3.0, "C03": 2.5, "C04": 2.0, "C05": 2.5, "C06": 1.8, "C07": 2.0}

PRESETS = {
    "2025 repeat": dict(budgets={"C01": 42000, "C02": 93000, "C03": 59000, "C04": 31000, "C05": 19000, "C06": 14000, "C07": 16000},
                        show_uplift=0.0, reg_uplift=0.0),
    "Base": dict(budgets={"C01": 52000, "C02": 70000, "C03": 40000, "C04": 45000, "C05": 28000, "C06": 17000, "C07": 20000},
                 show_uplift=0.03, reg_uplift=0.0),
    "Stretch": dict(budgets={"C01": 62000, "C02": 55000, "C03": 28000, "C04": 58000, "C05": 38000, "C06": 18000, "C07": 25000},
                    show_uplift=0.08, reg_uplift=0.02),
}


def baseline(d=None):
    d = d or A.latest_date()
    rows = {r["campaign_id"]: r for r in A.campaigns_table(d)}
    base = {}
    for cid in BETA:
        r = rows[cid]
        base[cid] = dict(name=r["name"], S0=r["spend"], I0=r["identified"], reg_rate=r["reg_rate"], show_rate=r["show_rate"])
    walk = rows.get("UNATTR", {}).get("attended", 0)
    return base, walk


def run(budgets, show_uplift=0.0, reg_uplift=0.0, walkins=None, d=None):
    base, walk = baseline(d)
    walk = walk if walkins is None else walkins
    out, tot = [], dict(spend=0, identified=0, registered=0, attended=0)
    for cid, b in base.items():
        S = float(budgets.get(cid, b["S0"]))
        ratio = min(S / b["S0"], CAP[cid]) if b["S0"] else 0
        ident = b["I0"] * (ratio ** BETA[cid])
        regr = min(b["reg_rate"] + reg_uplift, 0.97)
        showr = min(b["show_rate"] + show_uplift, 0.95)
        reg = ident * regr
        att = reg * showr
        capped = (S / b["S0"]) > CAP[cid] if b["S0"] else False
        out.append(dict(campaign_id=cid, name=b["name"], spend=round(S), identified=round(ident), registered=round(reg),
                        attended=round(att), cpa=round(S / att, 1) if att else None, show_rate=round(showr, 3), capped=capped))
        tot["spend"] += S
        tot["identified"] += ident
        tot["registered"] += reg
        tot["attended"] += att
    tot["attended"] += walk
    tot["identified"] += walk
    res = dict(campaigns=out, walkins=walk, total={k: round(v) for k, v in tot.items()})
    res["total"]["cpa"] = round(tot["spend"] / tot["attended"], 1)
    return res


def preset(name):
    p = PRESETS[name]
    return run(p["budgets"], p["show_uplift"], p["reg_uplift"])


if __name__ == "__main__":
    for n in PRESETS:
        r = preset(n)
        print(n, r["total"])
        for c in r["campaigns"]:
            print("   ", c["campaign_id"], c["spend"], c["attended"], c["cpa"], "CAP" if c["capped"] else "")
