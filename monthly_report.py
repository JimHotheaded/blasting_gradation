#!/usr/bin/env python3
"""Monthly blast-fragmentation report, English and Thai, HTML + PDF + CSV.

Reads every daily report in output/<YYYY-MM>/<YYYY-MM-DD>/ and writes
output/<YYYY-MM>/report/. Per-day judgements (confidence, plausible range, notes)
come from output/<YYYY-MM>/report/notes.json, which a person writes after reviewing
each day's overlay; they cannot be computed from the JSON.

    python monthly_report.py 2026-09               # build (latest month if omitted)
    python monthly_report.py 2026-10 --init-notes  # write a notes.json stub to fill in

Split convention: 100 mm is the low cut point. "<100 mm" is a share of all
material; crusher (100-400 mm) and breaker (>=400 mm) are shares of the rock above
the cut point, so they add up to 100%. Monthly figures use only days whose
confidence is not "provisional".
"""
import argparse, base64, csv, datetime, html, json, math, re, statistics, subprocess, sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

CUT, BREAKER = 100, 400
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]
TH_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม",
             "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
TH_ABBR = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.",
           "พ.ย.", "ธ.ค."]
BE = 543
CONFS = ("good", "fair", "low", "provisional")
CONF_ICON = {"good": ("✓", "status-good"), "fair": ("!", "status-warn"),
             "low": ("✕", "status-serious"), "provisional": ("?", "status-serious")}
SERIES = ["s1", "s2", "s3", "s4", "s5", "s6"]      # validated categorical slots
EDGE_PATHS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]


def month_text(month, prepared):
    """Every piece of wording, per language. Month-specific parts are computed."""
    y, m = int(month[:4]), int(month[5:7])
    py, pm, pd = int(prepared[:4]), int(prepared[5:7]), int(prepared[8:10])
    en_m, th_m = EN_MONTHS[m-1], TH_MONTHS[m-1]
    return {
"en": dict(
    lang="en", extra_css="\n@media print { .lede { break-after:avoid } }",
    font='system-ui,-apple-system,"Segoe UI",sans-serif', lh="1.5",
    short=lambda d: f"{int(d[8:])} {en_m[:3]}", long=lambda d: f"{int(d[8:])} {en_m[:3]} {y}",
    day_name=lambda d: f"{int(d[8:])} {en_m}",
    title=f"Blast fragmentation, {en_m} {y}",
    h1=f"Blast fragmentation: {en_m} {y}",
    sub="{n} production days, photo-based gradation from rock_gradation.py. "
        f"Report prepared {pd} {EN_MONTHS[pm-1]} {py}.",
    tiles_aria="Monthly headline figures",
    sum_h="Summary",
    sum_first=["Across the {m} days with a measured scale, a median {medb:.1f}% of the rock above the 100 mm cut point needed the breaker, ranging from {bmin:.0f}% to {bmax:.0f}% between days. The crusher took a median {medc:.0f}% of that rock.",
               "A median {medf:.0f}% (mean {meanf:.0f}%) of all material was below the 100 mm cut point (range {fmin:.0f}-{fmax:.0f}%)."],
    sum_last=["Figures are indicative: accuracy has not been checked against physical measurement of the same material."],
    t1="Median breaker share", t1h="of rock above 100 mm, {m} measured days",
    t2="Breaker range", t2h="of rock above 100 mm",
    t5="Mean below 100 mm", t5h="of all material, {m} measured days",
    t3="Median D50", t3h="half the material is finer than this", mm="mm",
    t4="Days analysed",
    t4h={"none": "{m} measured", "pole": "{m} measured, {p} provisional (no pole)",
         "other": "{m} measured, {p} provisional"},
    prov_bullet={"pole": ["{days} is provisional: it had no pole, so its scale is estimated and it is left out of these figures.",
                          "{days} are provisional: they had no pole, so their scale is estimated and they are left out of these figures."],
                 "other": ["{days} is provisional and left out of these figures.",
                           "{days} are provisional and left out of these figures."]},
    h2a="Oversize material by day",
    ledea="Share of the rock above the 100 mm cut point that is 400 mm and over, and so goes to the hydraulic breaker. Bars show the\nplausible range where one choice changed the answer; the hollow dot has no measured scale.",
    h2c="Size distribution",
    ledec="Cumulative percent passing, as reported (fines below 100 mm come from the Rosin-Rammler fit).\nCurves further left are finer.",
    hover=" Hover to compare all days at one size.",
    prov="provisional", summary="Show as table", size_head="Size mm",
    each_day="each day", median_curve="monthly median", tmin="min", tmed="median", tmax="max",
    h2d="Daily results",
    leded="Sizes in millimetres. The &lt;100 mm column is the share of all material below the 100 mm cut point. Crusher (100-400 mm) and breaker (400 mm and over) are shares of the rock above the cut point, so they add up to 100%.",
    heads=["Day", "Confidence", "mm/px", "Fragments", "Delineated", "D10", "D50", "D80", "Top size",
           "Cu", "&lt;100 mm", "Crusher", "Breaker", "Oversize blocks"],
    h2e="Day by day",
    ledee="Segmentation overlays: red 400 mm and over, orange 300-400, green 100-300, blue under 100.",
    h2f="Method and limits",
    scale_all="Scale comes from the red and white pole.",
    scale_except="Scale comes from the red and white pole, except on {days}, where it\ncomes from a line drawn on one block and assumed to be {cm} cm.",
    and_="and",
    method=[
        "Each day is one photo of the muckpile surface. Blocks are outlined by FastSAM, sized by the short axis of\ntheir best-fit ellipse, and weighted by visible area. {scale}",
        "Days are not pooled into a single monthly gradation: they are different piles, photographed from different\ndistances with different areas. Monthly figures are medians of the daily results.",
        "Only the surface is visible, and it is coarser than the pile's interior. Rock nearer the camera than the pole\nreads too large; none of these photos had a perspective calibration.",
        "Crusher and breaker shares are of the rock above the 100 mm cut point; material below it is reported separately, as a share of all material.",
        "Size is measured on the short axis. A long flat slab can count as crusher feed even when it is over 400 mm long.",
        "Accuracy is unvalidated. These figures have not been compared against physical sieving or measurement of\nthe same material, and should be treated as indicative."],
    ca_title="Breaker share by production day",
    cc_title="Cumulative percent passing by size, one curve per day",
    fines="fines &lt;100 mm (model)", xaxis="Size (mm), log scale", breaker_ref="breaker 400 mm",
    aria_hit="Hover or use arrow keys to read values",
    tip_blocks="{n} oversize blocks", tip_range="plausible range {r}", tip_curve="{s} mm passing",
    scale_pole="pole", scale_line="drawn line, assumed {cm:g} cm", whole="whole frame",
    alt="Segmentation overlay for {d}",
    facts="<span class=\"strong\">{b:.1f}%</span> breaker &middot; D50 {d50:.0f} mm &middot;\n{n} fragments &middot; {mmpp:.2f} mm/px ({scale}) &middot; ROI {roi}",
    conf={"good": "Good", "fair": "Fair", "low": "Low", "provisional": "Provisional"},
),
"th": dict(
    lang="th",
    extra_css="\n@media print { table { line-height:1.3 } .lede { break-after:avoid } }",
    font='"Leelawadee UI",Leelawadee,Tahoma,system-ui,sans-serif', lh="1.65",
    short=lambda d: f"{int(d[8:])} {TH_ABBR[m-1]}",
    long=lambda d: f"{int(d[8:])} {th_m} {y + BE}",
    day_name=lambda d: f"{int(d[8:])} {th_m}",
    title=f"การแตกหักของหินจากการระเบิด {th_m} {y + BE}",
    h1=f"การแตกหักของหินจากการระเบิด: {th_m} {y + BE}",
    sub="{n} วันการผลิต วิเคราะห์ขนาดหินจากภาพถ่ายด้วย rock_gradation.py "
        f"จัดทำเมื่อ {pd} {TH_MONTHS[pm-1]} {py + BE}",
    tiles_aria="ตัวเลขสรุปประจำเดือน",
    sum_h="สรุป",
    sum_first=["จาก {m} วันที่มีมาตราส่วนวัดจริง ค่ามัธยฐานของหินที่ใหญ่กว่าจุดตัด 100 มม. ที่ต้องใช้เบรกเกอร์คือ {medb:.1f}% โดยแต่ละวันอยู่ในช่วง {bmin:.0f}% ถึง {bmax:.0f}% และเข้าเครื่องโม่เป็นค่ามัธยฐาน {medc:.0f}%",
               "วัสดุที่เล็กกว่าจุดตัด 100 มม. มีค่ามัธยฐาน {medf:.0f}% (ค่าเฉลี่ย {meanf:.0f}%) ของวัสดุทั้งหมด (ช่วง {fmin:.0f}-{fmax:.0f}%)"],
    sum_last=["ตัวเลขเป็นค่าบ่งชี้ ยังไม่ได้ตรวจสอบความแม่นยำเทียบกับการวัดจริงของวัสดุเดียวกัน"],
    t1="ค่ามัธยฐานเบรกเกอร์", t1h="ของหินที่ใหญ่กว่า 100 มม. จาก {m} วันที่มีมาตราส่วนวัดจริง",
    t2="ช่วงเบรกเกอร์รายวัน", t2h="ของหินที่ใหญ่กว่า 100 มม.",
    t5="ค่าเฉลี่ยต่ำกว่า 100 มม.", t5h="ของวัสดุทั้งหมด จาก {m} วันที่วัดจริง",
    t3="ค่ามัธยฐาน D50", t3h="วัสดุครึ่งหนึ่งมีขนาดเล็กกว่าค่านี้", mm="มม.",
    t4="จำนวนวันที่วิเคราะห์",
    t4h={"none": "วัดจริง {m} วัน", "pole": "วัดจริง {m} วัน เบื้องต้น {p} วัน (ไม่มีไม้สเกล)",
         "other": "วัดจริง {m} วัน เบื้องต้น {p} วัน"},
    prov_bullet={"pole": ["วันที่ {days}เป็นผลเบื้องต้น เนื่องจากไม่มีไม้สเกลในภาพ จึงประมาณมาตราส่วนและไม่นำมาคำนวณตัวเลขเหล่านี้"] * 2,
                 "other": ["วันที่ {days}เป็นผลเบื้องต้นและไม่นำมาคำนวณตัวเลขเหล่านี้"] * 2},
    h2a="หินเกินขนาดรายวัน",
    ledea="สัดส่วนของหินที่ใหญ่กว่าจุดตัด 100 มม. ซึ่งมีขนาด 400 มม. ขึ้นไป และต้องใช้เบรกเกอร์ไฮดรอลิกทุบ แถบแนวตั้งแสดงช่วงค่าที่เป็นไปได้ในวันที่การตัดสินใจหนึ่งเปลี่ยนผลลัพธ์ จุดกลวงคือวันที่ไม่มีมาตราส่วนวัดจริง",
    h2c="การกระจายขนาด",
    ledec="เปอร์เซ็นต์ผ่านสะสมตามที่รายงาน (วัสดุละเอียดต่ำกว่า 100 มม. ได้จากแบบจำลอง Rosin-Rammler) เส้นที่อยู่ทางซ้ายมากกว่าคือหินที่ละเอียดกว่า",
    hover=" วางเมาส์เพื่อเปรียบเทียบทุกวันที่ขนาดเดียวกัน",
    prov="เบื้องต้น", summary="แสดงเป็นตาราง", size_head="ขนาด (มม.)",
    each_day="แต่ละวัน", median_curve="ค่ามัธยฐานของเดือน", tmin="ต่ำสุด", tmed="มัธยฐาน", tmax="สูงสุด",
    h2d="ผลรายวัน",
    leded="ขนาดเป็นมิลลิเมตร คอลัมน์ &lt;100 มม. คือสัดส่วนของวัสดุทั้งหมดที่เล็กกว่าจุดตัด 100 มม. ส่วนเครื่องโม่ (100-400 มม.) และเบรกเกอร์ (400 มม. ขึ้นไป) คิดเป็นสัดส่วนของหินที่ใหญ่กว่าจุดตัด จึงรวมกันได้ 100%",
    heads=["วันที่", "ความเชื่อมั่น", "mm/px", "จำนวนก้อน", "พื้นที่ตรวจจับ", "D10", "D50", "D80",
           "ขนาดใหญ่สุด", "Cu", "&lt;100 มม.", "เครื่องโม่", "เบรกเกอร์", "ก้อนเกินขนาด"],
    h2e="รายละเอียดแต่ละวัน",
    ledee="ภาพการแบ่งส่วน: สีแดง 400 มม. ขึ้นไป สีส้ม 300-400 สีเขียว 100-300 และสีน้ำเงินต่ำกว่า 100",
    h2f="วิธีการและข้อจำกัด",
    scale_all="มาตราส่วนได้จากไม้สเกลสีแดง-ขาว",
    scale_except="มาตราส่วนได้จากไม้สเกลสีแดง-ขาว ยกเว้นวันที่ {days}ที่ได้จากเส้นที่วาดบนหินหนึ่งก้อนโดยสมมติว่ายาว {cm} ซม.",
    and_="และ",
    method=[
        "แต่ละวันใช้ภาพถ่ายผิวกองหินหนึ่งภาพ ขอบเขตของก้อนหินตรวจจับด้วย FastSAM วัดขนาดจากแกนสั้นของวงรีที่เข้ากันที่สุด และถ่วงน้ำหนักด้วยพื้นที่ที่มองเห็น {scale}",
        "ไม่ได้รวมข้อมูลทุกวันเป็นเส้นการกระจายขนาดเดียวของเดือน เพราะเป็นกองหินต่างกัน ถ่ายจากระยะและพื้นที่ที่ต่างกัน ตัวเลขประจำเดือนจึงเป็นค่ามัธยฐานของผลรายวัน",
        "มองเห็นได้เฉพาะผิวกอง ซึ่งหยาบกว่าเนื้อในของกอง หินที่อยู่ใกล้กล้องกว่าไม้สเกลจะวัดได้ใหญ่เกินจริง และไม่มีภาพใดที่ได้รับการสอบเทียบมุมมอง",
        "สัดส่วนเครื่องโม่และเบรกเกอร์คิดจากหินที่ใหญ่กว่าจุดตัด 100 มม. ส่วนวัสดุที่เล็กกว่ารายงานแยกเป็นสัดส่วนของวัสดุทั้งหมด",
        "ขนาดวัดตามแกนสั้น แผ่นหินแบนยาวอาจถูกนับเป็นวัสดุเข้าเครื่องโม่ แม้จะยาวเกิน 400 มม.",
        "ยังไม่ได้ตรวจสอบความแม่นยำ ตัวเลขเหล่านี้ยังไม่ได้เปรียบเทียบกับการร่อนตะแกรงหรือการวัดจริงของวัสดุเดียวกัน จึงควรใช้เป็นค่าบ่งชี้เท่านั้น"],
    ca_title="สัดส่วนเบรกเกอร์ตามวันการผลิต",
    cc_title="เปอร์เซ็นต์ผ่านสะสมตามขนาด แยกเส้นตามวัน",
    fines="วัสดุละเอียด &lt;100 มม. (แบบจำลอง)", xaxis="ขนาด (มม.) สเกลลอการิทึม",
    breaker_ref="เบรกเกอร์ 400 มม.",
    aria_hit="วางเมาส์หรือใช้ปุ่มลูกศรเพื่ออ่านค่า",
    tip_blocks="หินเกินขนาด {n} ก้อน", tip_range="ช่วงที่เป็นไปได้ {r}", tip_curve="ผ่านตะแกรง {s} มม.",
    scale_pole="ไม้สเกล", scale_line="เส้นที่วาด สมมติ {cm:g} ซม.", whole="ทั้งภาพ",
    alt="ภาพการแบ่งส่วนของวันที่ {d}",
    facts="เบรกเกอร์ <span class=\"strong\">{b:.1f}%</span> &middot; D50 {d50:.0f} มม. &middot;\n{n} ก้อน &middot; {mmpp:.2f} mm/px <span style=\"white-space:nowrap\">({scale})</span> &middot; ROI {roi}",
    conf={"good": "ดี", "fair": "พอใช้", "low": "ต่ำ", "provisional": "เบื้องต้น"},
),
}


# ---------------------------------------------------------------- data
def day_folders(root):
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))


def load_day(root, day):
    stem = f"{day[5:7]}{day[8:10]}{day[:4]}"
    R = json.loads((root / day / f"{stem}_result.json").read_text(encoding="utf-8"))
    overlay = next((root / day).glob(f"{stem}_overlay.*"), None)
    thumb = ""
    if overlay is not None:
        ov = cv2.imdecode(np.fromfile(str(overlay), np.uint8), cv2.IMREAD_COLOR)
        k = 560 / ov.shape[1]
        small = cv2.resize(ov, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".webp", small, [cv2.IMWRITE_WEBP_QUALITY, 72])
        thumb = base64.b64encode(buf.tobytes()).decode()
    pas = {q["size_mm"]: q["report"] for q in R["passing"]}
    above = max(100 - pas[CUT], 1e-9)             # rock above the cut point
    R["split"] = dict(bypass=round(pas[CUT], 2),                                  # % of all
                      crusher=round(100 * (pas[BREAKER] - pas[CUT]) / above, 2),  # % of >=CUT
                      breaker=round(100 * (100 - pas[BREAKER]) / above, 2))
    return R, thumb


def init_notes(root, path):
    days = day_folders(root)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"days": {}}
    for day in days:
        old["days"].setdefault(day, {"conf": "REVIEW", "notes": {"en": [], "th": []}})
    old.setdefault("highlights", {"en": [], "th": []})
    old["_about"] = ("Per-day judgements for the monthly report, written while reviewing each "
                     "day. conf: good | fair | low | provisional. range: plausible breaker range "
                     "in % of rock above 100 mm. flag: short label shown under the day on the "
                     "oversize chart. highlights: month-specific summary bullets.")
    path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    todo = [d for d, e in old["days"].items() if e.get("conf") not in CONFS]
    print(f"wrote {path}: {len(days)} days, {len(todo)} to review: {', '.join(todo) or 'none'}")


# ---------------------------------------------------------------- charts
def chart_breaker(days, L):
    W, H, L_, R_, T, B = 720, 300, 52, 20, 24, 58
    pw, ph = W - L_ - R_, H - T - B
    top = max([d["R"]["split"]["breaker"] for d in days] +
              [d["meta"]["range"][1] for d in days if "range" in d["meta"]])
    ymax = max(40.0, math.ceil(top / 10) * 10)
    y = lambda v: T + ph * (1 - v / ymax)
    band = pw / len(days)
    x = lambda i: L_ + band * (i + 0.5)
    every = max(1, math.ceil(len(days) / 12))     # thin date labels on busy months
    esc = html.escape
    s = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="ca-t">'
         f'<title id="ca-t">{L["ca_title"]}</title>']
    for v in range(0, int(ymax) + 1, 10):
        cls = "axis" if v == 0 else "grid"
        s.append(f'<line class="{cls}" x1="{L_}" x2="{W-R_}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                 f'<text class="tick" x="{L_-8}" y="{y(v)+4:.1f}" text-anchor="end">{v}%</text>')
    for i, d in enumerate(days):
        b, m, cx = d["R"]["split"]["breaker"], d["meta"], x(i)
        if "range" in m:
            lo, hi = m["range"]
            s.append(f'<line class="range" x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(lo):.1f}" y2="{y(hi):.1f}"/>')
        cls = "dot hollow" if m["conf"] == "provisional" else "dot"
        s.append(f'<circle class="{cls}" cx="{cx:.1f}" cy="{y(b):.1f}" r="5"/>')
        rng = f"{m['range'][0]:.1f}-{m['range'][1]:.1f}%" if "range" in m else ""
        tip = json.dumps(dict(title=d["long"], value=f"{b:.1f}%",
                              lines=[L["tip_blocks"].format(n=d['R']['oversize_blocks']),
                                     *([L["tip_range"].format(r=rng)] if rng else []),
                                     *([d["flag"]] if d.get("flag") else [])]))
        s.append(f'<circle class="hit" cx="{cx:.1f}" cy="{y(b):.1f}" r="16" tabindex="0" '
                 f"data-tip='{esc(tip, quote=True)}'/>")
        if i % every == 0:
            s.append(f'<text class="tick" x="{cx:.1f}" y="{H-B+20}" text-anchor="middle">{esc(d["label"])}</text>')
        if d.get("flag") and every == 1:
            s.append(f'<text class="note" x="{cx:.1f}" y="{H-B+36}" text-anchor="middle">{esc(d["flag"])}</text>')
    s.append("</svg>")
    return "".join(s)


def chart_curves(days, L, categorical):
    W, H, L_, R_, T, B = 720, 380, 52, 20, 20, 44
    pw, ph = W - L_ - R_, H - T - B
    lx0, lx1 = math.log10(10), math.log10(1200)
    x = lambda v: L_ + pw * (math.log10(v) - lx0) / (lx1 - lx0)
    y = lambda v: T + ph * (1 - v / 100)
    s = [f'<svg class="chart" id="curves" viewBox="0 0 {W} {H}" role="img" aria-labelledby="cc-t">'
         f'<title id="cc-t">{L["cc_title"]}</title>'
         f'<rect class="fines" x="{x(10):.1f}" y="{T}" width="{x(100)-x(10):.1f}" height="{ph}"/>'
         f'<text class="note" x="{x(10)+6:.1f}" y="{T+14}">{L["fines"]}</text>']
    for v in range(0, 101, 20):
        cls = "axis" if v == 0 else "grid"
        s.append(f'<line class="{cls}" x1="{L_}" x2="{W-R_}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                 f'<text class="tick" x="{L_-8}" y="{y(v)+4:.1f}" text-anchor="end">{v}%</text>')
    for v in (10, 25, 50, 100, 200, 400, 1000):
        s.append(f'<text class="tick" x="{x(v):.1f}" y="{H-B+18}" text-anchor="middle">{v}</text>')
    s.append(f'<text class="tick" x="{L_+pw/2:.1f}" y="{H-6}" text-anchor="middle">{L["xaxis"]}</text>')
    s.append(f'<line class="ref" x1="{x(400):.1f}" x2="{x(400):.1f}" y1="{T}" y2="{T+ph}"/>'
             f'<text class="note" x="{x(400)+6:.1f}" y="{T+ph-8}">{L["breaker_ref"]}</text>')
    pts = lambda vals, sizes: " ".join(f"{x(sz):.1f},{y(v):.1f}" for sz, v in zip(sizes, vals))
    sizes = [p["size_mm"] for p in days[0]["R"]["passing"]]
    for i, d in enumerate(days):
        vals = [p["report"] for p in d["R"]["passing"]]
        dash = ' stroke-dasharray="6 4"' if d["meta"]["conf"] == "provisional" else ""
        style = f'stroke:var(--{SERIES[i]})' if categorical else "stroke:var(--axis)"
        width = "" if categorical else ' stroke-width="1.2"'
        s.append(f'<polyline class="line" style="{style}"{width}{dash} points="{pts(vals, sizes)}"/>')
    if not categorical:
        med = [statistics.median(d["R"]["passing"][k]["report"] for d in days)
               for k in range(len(sizes))]
        s.append(f'<polyline class="line" style="stroke:var(--accent)" stroke-width="3" '
                 f'points="{pts(med, sizes)}"/>')
    s.append(f'<line id="xhair" class="xhair" x1="0" x2="0" y1="{T}" y2="{T+ph}" visibility="hidden"/>'
             f'<rect id="curves-hit" x="{L_}" y="{T}" width="{pw}" height="{ph}" fill="transparent" '
             f'tabindex="0" aria-label="{L["aria_hit"]}"/></svg>')
    return "".join(s), dict(L=L_, pw=pw, lx0=lx0, lx1=lx1)


# ---------------------------------------------------------------- page
CSS = """
.viz-root {{ color-scheme: light;
  --page:#f9f9f7; --surface-1:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10); --accent:#2a78d6;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300;
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; }}
@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) .viz-root {{ color-scheme: dark;
  --page:#0d0d0d; --surface-1:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --accent:#3987e5;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; }} }}
:root[data-theme="dark"] .viz-root {{ color-scheme: dark;
  --page:#0d0d0d; --surface-1:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --accent:#3987e5;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--page); }}
.viz-root {{ font-family:{font}; color:var(--ink);
  background:var(--page); line-height:{lh} }}
.wrap {{ max-width:980px; margin:0 auto; padding:32px 24px 64px }}
h1 {{ font-size:28px; margin:0 0 4px }} h2 {{ font-size:19px; margin:40px 0 4px }}
h3 {{ font-size:16px; margin:0 }}
.sub, .lede {{ color:var(--ink2); margin:0 }} .lede {{ margin:0 0 14px }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; margin:24px 0 8px }}
.tile {{ background:var(--surface-1); border:1px solid var(--border); border-radius:10px; padding:14px 16px }}
.tile .label {{ color:var(--ink2); font-size:13px }} .tile .value {{ font-size:30px; font-weight:600; white-space:nowrap }}
.tile .hint {{ color:var(--muted); font-size:12px }}
.panel {{ background:var(--surface-1); border:1px solid var(--border); border-radius:10px; padding:16px; position:relative }}
.chart {{ width:100%; height:auto; display:block; overflow:visible }}
.chart .grid {{ stroke:var(--grid); stroke-width:1 }} .chart .axis {{ stroke:var(--axis); stroke-width:1 }}
.chart .tick {{ fill:var(--muted); font-size:12px; font-variant-numeric:tabular-nums }}
.chart .note {{ fill:var(--ink2); font-size:11.5px }}
.chart .range {{ stroke:var(--accent); stroke-width:2; stroke-linecap:round; opacity:.45 }}
.chart .dot {{ fill:var(--accent); stroke:var(--surface-1); stroke-width:2 }}
.chart .dot.hollow {{ fill:var(--surface-1); stroke:var(--accent) }}
.chart .hit {{ fill:transparent; cursor:pointer; outline:none }}
.chart .hit:hover, .chart .hit:focus {{ fill:var(--accent); fill-opacity:.12 }}
.chart .line {{ fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round }}
.chart .fines {{ fill:var(--grid); opacity:.55 }} .chart .ref {{ stroke:var(--ink2); stroke-width:1 }}
.chart .xhair {{ stroke:var(--ink2); stroke-width:1 }}
.legend {{ display:flex; flex-wrap:wrap; gap:6px 18px; margin:0 0 10px; color:var(--ink2); font-size:13px }}
.key {{ display:inline-flex; align-items:center; gap:6px }}
.tip {{ position:absolute; pointer-events:none; background:var(--surface-1); border:1px solid var(--border);
  border-radius:8px; padding:8px 10px; font-size:12.5px; box-shadow:0 4px 16px rgba(0,0,0,.12);
  min-width:150px; z-index:5; display:none }}
.tip .t {{ color:var(--ink2); margin-bottom:4px }} .tip .v {{ font-weight:600; font-size:15px }}
.tip .row {{ display:flex; align-items:center; gap:8px; font-variant-numeric:tabular-nums }}
.tip .row b {{ min-width:44px; text-align:right }} .tip .m {{ color:var(--ink2) }}
table {{ width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums }}
th, td {{ padding:7px 8px; border-bottom:1px solid var(--grid); text-align:right; white-space:nowrap }}
th:first-child, td:first-child {{ text-align:left }} thead th {{ color:var(--ink2); font-weight:500 }}
.daily td:nth-child(2) {{ text-align:left }} .strong {{ font-weight:600 }}
.scroll {{ overflow-x:auto }}
.conf {{ display:inline-flex; align-items:center; gap:6px; color:var(--ink) }}
.badge {{ display:inline-grid; place-items:center; width:16px; height:16px; border-radius:50%;
  font-size:10px; font-weight:700; color:#0b0b0b }}
.status-good {{ background:var(--good); color:#fff }} .status-warn {{ background:var(--warn) }}
.status-serious {{ background:var(--serious) }}
details {{ margin-top:10px }} summary {{ cursor:pointer; color:var(--ink2); font-size:13px }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:14px }}
.card {{ background:var(--surface-1); border:1px solid var(--border); border-radius:10px; overflow:hidden }}
.card img {{ width:100%; height:220px; object-fit:contain; display:block; background:var(--page) }}
.card-body {{ padding:12px 14px }} .card-head {{ display:flex; justify-content:space-between; align-items:center }}
.facts {{ color:var(--ink2); font-size:13px; margin:6px 0 }}
.card ul {{ margin:0; padding-left:18px; font-size:13px; color:var(--ink) }} .card li {{ margin:3px 0 }}
.limits {{ font-size:13.5px; color:var(--ink2) }} .limits li {{ margin:4px 0 }}
.summary {{ margin-top:20px }} .summary h2 {{ margin:0 0 6px; font-size:17px }}
.summary ul {{ margin:0; padding-left:20px; font-size:14px }} .summary li {{ margin:4px 0 }}
@page {{ size:A4; margin:14mm 12mm }}
@media print {{ * {{ -webkit-print-color-adjust:exact; print-color-adjust:exact }}
  .wrap {{ padding:0; max-width:none }} .panel, .card, .tile, .tiles {{ break-inside:avoid }}
  h2 {{ break-after:avoid }} tr {{ break-inside:avoid }} .screen-only, summary, .tip {{ display:none }}
  .cards {{ grid-template-columns:1fr 1fr }} .card img {{ height:200px }}
  .viz-root {{ --page:#ffffff }} .tiles {{ grid-template-columns:repeat(5,1fr); gap:8px }} .tile {{ padding:10px 11px }}
  .tile .label {{ font-size:11px }} .tile .value {{ font-size:22px }} .tile .hint {{ font-size:10px }}
  .pb {{ break-before:page }} .scroll {{ overflow:visible }}
  table {{ font-size:10px }} th, td {{ padding:4px 5px }} thead th {{ white-space:normal; vertical-align:bottom }} }}{extra_css}
"""

SCRIPT = r"""
function showTip(tip, panel, clientX, clientY, build) {
  tip.replaceChildren(); build(tip); tip.style.display = "block";
  const r = panel.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  let x = clientX - r.left + 14, y = clientY - r.top - h - 10;
  if (x + w > r.width - 4) x = clientX - r.left - w - 14;
  if (y < 4) y = clientY - r.top + 16;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls;
  if (text != null) e.textContent = text; return e; }
// chart A: per-dot tooltip
const panelA = document.getElementById("panel-a"), tipA = document.getElementById("tip-a");
document.querySelectorAll("#panel-a .hit").forEach(h => {
  const d = JSON.parse(h.dataset.tip);
  const show = (cx, cy) => showTip(tipA, panelA, cx, cy, t => {
    t.append(el("div", "t", d.title), el("div", "v", d.value));
    d.lines.forEach(l => t.append(el("div", "m", l))); });
  h.addEventListener("pointermove", e => show(e.clientX, e.clientY));
  h.addEventListener("focus", () => { const b = h.getBoundingClientRect(); show(b.right, b.top); });
  h.addEventListener("pointerleave", () => tipA.style.display = "none");
  h.addEventListener("blur", () => tipA.style.display = "none");
});
// chart C: crosshair snaps to the nearest standard size; one tooltip lists every day
const svgC = document.getElementById("curves"), hitC = document.getElementById("curves-hit"),
      xh = document.getElementById("xhair"), panelC = document.getElementById("panel-c"),
      tipC = document.getElementById("tip-c"), G = CURVES.geo;
const xOf = v => G.L + G.pw * (Math.log10(v) - G.lx0) / (G.lx1 - G.lx0);
let idx = 7;
function drawAt(i, cx, cy) {
  idx = i; const sx = xOf(CURVES.sizes[i]);
  xh.setAttribute("x1", sx); xh.setAttribute("x2", sx); xh.setAttribute("visibility", "visible");
  showTip(tipC, panelC, cx, cy, t => {
    t.append(el("div", "t", CURVES.tip.replace("{s}", CURVES.sizes[i])));
    CURVES.series.forEach(s => { const row = el("div", "row");
      const k = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      k.setAttribute("width", "14"); k.setAttribute("height", "8");
      const ln = document.createElementNS("http://www.w3.org/2000/svg", "line");
      ln.setAttribute("x1", "1"); ln.setAttribute("x2", "13"); ln.setAttribute("y1", "4"); ln.setAttribute("y2", "4");
      ln.setAttribute("stroke-width", "2"); ln.setAttribute("stroke-linecap", "round");
      ln.style.stroke = "var(--" + s.var + ")"; k.append(ln);
      row.append(k, el("b", null, s.values[i].toFixed(1) + "%"), el("span", "m", s.name)); t.append(row); });
  });
}
hitC.addEventListener("pointermove", e => {
  const p = svgC.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
  const vx = p.matrixTransform(svgC.getScreenCTM().inverse()).x;
  let best = 0, bd = 1e9;
  CURVES.sizes.forEach((s, i) => { const dd = Math.abs(xOf(s) - vx); if (dd < bd) { bd = dd; best = i; } });
  drawAt(best, e.clientX, e.clientY);
});
const hideC = () => { tipC.style.display = "none"; xh.setAttribute("visibility", "hidden"); };
hitC.addEventListener("pointerleave", hideC); hitC.addEventListener("blur", hideC);
hitC.addEventListener("focus", () => { const b = hitC.getBoundingClientRect(); drawAt(idx, b.left + b.width / 2, b.top + 30); });
hitC.addEventListener("keydown", e => {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return; e.preventDefault();
  const i = Math.max(0, Math.min(CURVES.sizes.length - 1, idx + (e.key === "ArrowRight" ? 1 : -1)));
  const b = svgC.getBoundingClientRect(), sx = xOf(CURVES.sizes[i]) / 720 * b.width + b.left;
  drawAt(i, sx, b.top + 30);
});
"""


def join_days(names, and_):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" {and_} " + names[-1]


def build(lang, month, root, notes, raw, prepared):
    L = month_text(month, prepared)[lang]
    esc = html.escape
    PROV = f" ({L['prov']})"
    days = []
    for day, (R, thumb) in raw.items():
        e = notes["days"][day]
        meta = dict(conf=e["conf"], notes=e["notes"][lang])
        if "range" in e:
            meta["range"] = e["range"]
        days.append(dict(day=day, label=L["short"](day), long=L["long"](day), R=R, meta=meta,
                         thumb=thumb, flag=(e.get("flag") or {}).get(lang)))

    measured = [d for d in days if d["meta"]["conf"] != "provisional"]
    if not measured:
        sys.exit("Every day is provisional; there is nothing to summarise.")
    brk = [d["R"]["split"]["breaker"] for d in measured]
    fines = [d["R"]["split"]["bypass"] for d in measured]
    st = dict(m=len(measured), medb=statistics.median(brk), bmin=min(brk), bmax=max(brk),
              medc=statistics.median(d["R"]["split"]["crusher"] for d in measured),
              medf=statistics.median(fines), meanf=statistics.mean(fines),
              fmin=min(fines), fmax=max(fines))
    med_d50 = statistics.median(d["R"]["d_values"]["D50"] for d in measured)
    n_prov = len(days) - len(measured)

    categorical = len(days) <= len(SERIES)
    svg_a = chart_breaker(days, L)
    svg_c, geo = chart_curves(days, L, categorical)
    sizes = [p["size_mm"] for p in days[0]["R"]["passing"]]
    if categorical:
        series = [dict(name=d["label"] + (PROV if d["meta"]["conf"] == "provisional" else ""),
                       var=SERIES[i], values=[p["report"] for p in d["R"]["passing"]])
                  for i, d in enumerate(days)]
    else:
        cols = [[d["R"]["passing"][k]["report"] for d in days] for k in range(len(sizes))]
        series = [dict(name=L["tmin"], var="axis", values=[min(c) for c in cols]),
                  dict(name=L["tmed"], var="accent", values=[statistics.median(c) for c in cols]),
                  dict(name=L["tmax"], var="axis", values=[max(c) for c in cols])]
    curve_data = dict(sizes=sizes, series=series, geo=geo, tip=L["tip_curve"])

    def key(style, text, dash=""):
        return (f'<span class="key"><svg width="22" height="10"><line x1="1" x2="21" y1="5" y2="5" '
                f'style="{style}" stroke-width="2" stroke-linecap="round"{dash}/></svg>{text}</span>')
    if categorical:
        legend = "".join(key(f"stroke:var(--{SERIES[i]})",
                             esc(d["label"]) + (PROV if d["meta"]["conf"] == "provisional" else ""),
                             ' stroke-dasharray="4 3"' if d["meta"]["conf"] == "provisional" else "")
                         for i, d in enumerate(days))
    else:
        legend = key("stroke:var(--axis)", L["each_day"]) + key("stroke:var(--accent)", L["median_curve"])

    def conf_cell(c):
        icon, cls = CONF_ICON[c]
        return (f'<span class="conf"><span class="badge {cls}" aria-hidden="true">{icon}</span>'
                f'{L["conf"][c]}</span>')
    fmt = lambda v, n=0: "-" if v is None else f"{v:.{n}f}"

    rows = []
    for d in days:
        R = d["R"]
        rows.append(f"""<tr><th scope="row">{esc(d['label'])}</th><td>{conf_cell(d['meta']['conf'])}</td>
<td>{R['mm_per_px']:.2f}</td><td>{R['fragments']}</td><td>{R['delineated_pct']:.0f}%</td>
<td>{fmt(R['d_values']['D10'])}</td><td>{fmt(R['d_values']['D50'])}</td><td>{fmt(R['d_values']['D80'])}</td>
<td>{fmt(R['top_size_mm'])}</td><td>{R['Cu']:.1f}</td><td>{R['split']['bypass']:.1f}%</td>
<td>{R['split']['crusher']:.1f}%</td><td class="strong">{R['split']['breaker']:.1f}%</td>
<td>{R['oversize_blocks']}</td></tr>""")

    curve_rows = []
    for i, sz in enumerate(sizes):
        cells = "".join(f"<td>{s['values'][i]:.1f}</td>" for s in series)
        curve_rows.append(f"<tr><th scope='row'>{sz}</th>{cells}</tr>")
    curve_head = "".join(f"<th scope='col'>{esc(d['label'] if categorical else s['name'])}</th>"
                         for d, s in zip(days if categorical else series, series))

    def scale_label(R):
        if R["scale_method"].startswith("manual --pole-px"):
            return L["scale_line"].format(cm=R["settings"]["pole_length"] / 10)
        return L["scale_pole"] if R["scale_method"].startswith("auto pole") else R["scale_method"]

    cards = []
    for d in days:
        R, m = d["R"], d["meta"]
        notes_html = "".join(f"<li>{esc(n)}</li>" for n in m["notes"])
        roi = ", ".join(f"{v:g}" for v in R["settings"]["roi"]) if R["settings"]["roi"] else L["whole"]
        facts = L["facts"].format(b=R["split"]["breaker"], d50=R["d_values"]["D50"], n=R["fragments"],
                                  mmpp=R["mm_per_px"], scale=esc(scale_label(R)), roi=esc(roi))
        img = (f'<img src="data:image/webp;base64,{d["thumb"]}"\nalt="{esc(L["alt"].format(d=d["label"]))}" '
               f'loading="lazy">') if d["thumb"] else ""
        cards.append(f"""<article class="card">{img}
<div class="card-body"><div class="card-head"><h3>{esc(d['long'])}</h3>{conf_cell(m['conf'])}</div>
<p class="facts">{facts}</p>
<ul>{notes_html}</ul></div></article>""")

    drawn = [d for d in days if d["R"]["scale_method"].startswith("manual --pole-px")]
    if drawn:
        cms = sorted({d["R"]["settings"]["pole_length"] / 10 for d in drawn})
        scale = L["scale_except"].format(days=join_days([L["day_name"](d["day"]) for d in drawn], L["and_"]),
                                         cm=" / ".join(f"{c:g}" for c in cms))
    else:
        scale = L["scale_all"]
    method = "".join(f"<li>{m.format(scale=scale) if '{scale}' in m else m}</li>\n" for m in L["method"])
    prov_days = [d for d in days if d["meta"]["conf"] == "provisional"]
    why = "pole" if prov_days and all(d["R"]["scale_method"].startswith("manual") for d in prov_days) else "other"
    prov = ([L["prov_bullet"][why][len(prov_days) > 1].format(
                days=join_days([L["day_name"](d["day"]) for d in prov_days], L["and_"]))]
            if prov_days else [])
    t4h = L["t4h"]["none" if not prov_days else why].format(m=st["m"], p=n_prov)
    bullets = ([s.format(**st) for s in L["sum_first"]] + list(notes.get("highlights", {}).get(lang, []))
               + prov + L["sum_last"])
    summary = "".join("<li>" + b + "</li>" for b in bullets)
    heads = "".join(f'<th scope="col">{h}</th>' for h in L["heads"])

    page = f"""<!doctype html><html lang="{L['lang']}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{L['title']}</title>
<style>{CSS.format(font=L['font'], lh=L['lh'], extra_css=L['extra_css'])}</style></head>
<body class="viz-root"><main class="wrap">
<h1>{L['h1']}</h1>
<p class="sub">{L['sub'].format(n=len(days))}</p>
<section class="summary panel"><h2>{L['sum_h']}</h2><ul>{summary}</ul></section>

<section class="tiles" aria-label="{L['tiles_aria']}">
 <div class="tile"><div class="label">{L['t1']}</div><div class="value">{st['medb']:.1f}%</div>
  <div class="hint">{L['t1h'].format(m=st['m'])}</div></div>
 <div class="tile"><div class="label">{L['t2']}</div><div class="value">{st['bmin']:.0f}-{st['bmax']:.0f}%</div>
  <div class="hint">{L['t2h']}</div></div>
 <div class="tile"><div class="label">{L['t5']}</div><div class="value">{st['meanf']:.1f}%</div>
  <div class="hint">{L['t5h'].format(m=st['m'])}</div></div>
 <div class="tile"><div class="label">{L['t3']}</div><div class="value">{med_d50:.0f} {L['mm']}</div>
  <div class="hint">{L['t3h']}</div></div>
 <div class="tile"><div class="label">{L['t4']}</div><div class="value">{len(days)}</div>
  <div class="hint">{t4h}</div></div>
</section>

<h2>{L['h2a']}</h2>
<p class="lede">{L['ledea']}</p>
<div class="panel" id="panel-a">{svg_a}<div class="tip" id="tip-a" role="status"></div></div>

<h2 class="pb">{L['h2c']}</h2>
<p class="lede">{L['ledec']}<span class="screen-only">{L['hover']}</span></p>
<div class="panel" id="panel-c"><div class="legend">{legend}</div>{svg_c}<div class="tip" id="tip-c" role="status"></div>
<details><summary>{L['summary']}</summary><div class="scroll"><table>
<thead><tr><th scope="col">{L['size_head']}</th>{curve_head}</tr></thead><tbody>{''.join(curve_rows)}</tbody></table></div></details></div>

<h2>{L['h2d']}</h2>
<p class="lede">{L['leded']}</p>
<div class="panel scroll"><table class="daily">
<thead><tr>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>

<h2>{L['h2e']}</h2>
<p class="lede">{L['ledee']}</p>
<section class="cards">{''.join(cards)}</section>

<h2>{L['h2f']}</h2>
<ul class="limits">
{method}</ul>
</main>
<script>
const CURVES = {json.dumps(curve_data, ensure_ascii=False)};
{SCRIPT}</script></body></html>"""
    return page, days, st


def write_csv(path, days, lang_conf):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["day", "confidence", "mm_per_px", "scale_method", "fragments", "delineated_pct",
                    "D10_mm", "D50_mm", "D80_mm", "top_size_mm", "Cu", "RR_xc_mm", "RR_n",
                    "lt100_pct_of_total", "crusher_pct_of_ge100", "breaker_pct_of_ge100",
                    "breaker_range_pct", "oversize_blocks", "notes"])
        for d in days:
            R, m = d["R"], d["meta"]
            w.writerow([d["day"], lang_conf[m["conf"]], round(R["mm_per_px"], 4), R["scale_method"],
                        R["fragments"], R["delineated_pct"], R["d_values"]["D10"], R["d_values"]["D50"],
                        R["d_values"]["D80"], R["top_size_mm"], R["Cu"],
                        R["rosin_rammler"]["xc_mm"] and round(R["rosin_rammler"]["xc_mm"], 1),
                        R["rosin_rammler"]["n"] and round(R["rosin_rammler"]["n"], 3),
                        R["split"]["bypass"], R["split"]["crusher"], R["split"]["breaker"],
                        f"{m['range'][0]}-{m['range'][1]}" if "range" in m else "",
                        R["oversize_blocks"], " | ".join(m["notes"])])


def print_pdf(html_text, lang, pdf_path):
    edge = next((p for p in EDGE_PATHS if Path(p).exists()), None)
    if edge is None:
        print(f"  PDF skipped: Microsoft Edge not found; open {pdf_path.with_suffix('.html')} and print to PDF")
        return False
    printable = (html_text.replace(f'<html lang="{lang}">', f'<html lang="{lang}" data-theme="light">')
                          .replace("<details>", "<details open>"))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "print.html"
        src.write_text(printable, encoding="utf-8")
        subprocess.run([edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf_path.resolve()}", src.as_uri()],
                       capture_output=True, timeout=180)
    return pdf_path.exists()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("month", nargs="?", help="YYYY-MM (default: latest month in output/)")
    ap.add_argument("--output", type=Path, default=Path("output"))
    ap.add_argument("--lang", nargs="+", default=["en", "th"], choices=["en", "th"])
    ap.add_argument("--prepared", default=datetime.date.today().isoformat(), help="report date, YYYY-MM-DD")
    ap.add_argument("--init-notes", action="store_true", help="write/extend notes.json and stop")
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args(argv)

    months = sorted(p.name for p in args.output.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}", p.name))
    month = args.month or (months[-1] if months else None)
    if month not in months:
        sys.exit(f"No month folder {args.output / str(month)}; found: {', '.join(months) or 'none'}")
    root = args.output / month
    out = root / "report"
    out.mkdir(exist_ok=True)
    notes_path = out / "notes.json"
    if args.init_notes:
        init_notes(root, notes_path)
        return 0

    days = day_folders(root)
    if not days:
        sys.exit(f"No daily reports in {root}")
    if not notes_path.exists():
        sys.exit(f"Missing {notes_path}. Run with --init-notes, then review each day and fill it in.")
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    missing = [d for d in days if notes["days"].get(d, {}).get("conf") not in CONFS]
    if missing:
        sys.exit(f"notes.json has no reviewed entry (conf = {' | '.join(CONFS)}) for: {', '.join(missing)}")

    raw = {d: load_day(root, d) for d in days}
    for lang in args.lang:
        suffix = "" if lang == "en" else f"_{lang}"
        page, built, st = build(lang, month, root, notes, raw, args.prepared)
        html_path = out / f"{month}_report{suffix}.html"
        html_path.write_text(page, encoding="utf-8")
        msg = f"[{lang}] {html_path}"
        if not args.no_pdf:
            pdf = out / f"{month}_report{suffix}.pdf"
            msg += f" + {pdf.name}" if print_pdf(page, lang, pdf) else " (PDF failed)"
        print(msg)
        if lang == "en" or "en" not in args.lang:
            write_csv(out / f"{month}_summary.csv", built, month_text(month, args.prepared)["en"]["conf"])
    print(f"{month}: {len(days)} days, {st['m']} measured | median breaker {st['medb']:.1f}% "
          f"({st['bmin']:.0f}-{st['bmax']:.0f}%) of rock >=100 mm | mean <100 mm {st['meanf']:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
