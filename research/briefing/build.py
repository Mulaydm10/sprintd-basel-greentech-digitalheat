import json
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image, Table,
                                TableStyle, PageBreak, KeepTogether, ListFlowable, ListItem)

F = "/usr/share/fonts/TTF/"
pdfmetrics.registerFont(TTFont("D", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DB", F + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DM", F + "DejaVuSansMono.ttf"))
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily("D", normal="D", bold="DB", italic="D", boldItalic="DB")

N = json.load(open("numbers.json"))
FO = N["sweep"]["follow"]; AL = N["sweep"]["always"]
ACC = colors.HexColor("#d9480f"); INK = colors.HexColor("#212529"); MUT = colors.HexColor("#6c757d"); BG = colors.HexColor("#f8f9fa")

ss = {
 "t": ParagraphStyle("t", fontName="DB", fontSize=24, leading=29, textColor=INK, spaceAfter=6),
 "st": ParagraphStyle("st", fontName="D", fontSize=12, leading=16, textColor=MUT, spaceAfter=14),
 "h1": ParagraphStyle("h1", fontName="DB", fontSize=15, leading=19, textColor=ACC, spaceBefore=10, spaceAfter=6),
 "h2": ParagraphStyle("h2", fontName="DB", fontSize=11.5, leading=15, textColor=INK, spaceBefore=8, spaceAfter=4),
 "b": ParagraphStyle("b", fontName="D", fontSize=9.3, leading=13.2, textColor=INK, spaceAfter=5),
 "s": ParagraphStyle("s", fontName="D", fontSize=7.8, leading=10.5, textColor=MUT, spaceAfter=4),
 "c": ParagraphStyle("c", fontName="DM", fontSize=8, leading=10.5, textColor=INK, backColor=BG, borderPadding=5, spaceBefore=3, spaceAfter=8, leftIndent=4),
 "box": ParagraphStyle("box", fontName="D", fontSize=9.3, leading=13.2, textColor=INK, backColor=colors.HexColor("#fff4e6"), borderColor=ACC, borderWidth=0.6, borderPadding=7, spaceBefore=6, spaceAfter=10),
 "tc": ParagraphStyle("tc", fontName="D", fontSize=8, leading=10.2, textColor=INK),
 "th": ParagraphStyle("th", fontName="DB", fontSize=8, leading=10.2, textColor=colors.white),
}
story = []
def h1(x): story.append(Paragraph(x, ss["h1"]))
def h2(x): story.append(Paragraph(x, ss["h2"]))
def p(x): story.append(Paragraph(x, ss["b"]))
def sm(x): story.append(Paragraph(x, ss["s"]))
def box(x): story.append(Paragraph(x, ss["box"]))
def code(x): story.append(Paragraph(x.replace("\n", "<br/>").replace(" ", "&nbsp;"), ss["c"]))
def bl(items):
    story.append(ListFlowable([ListItem(Paragraph(i, ss["b"]), leftIndent=10, value="•") for i in items], bulletType="bullet", start="•", leftIndent=12, bulletFontName="D"))
def img(f, w=170):
    story.append(Image(f, width=w * mm, height=w * mm * 0.36 if "jan" not in f and "jul" not in f else w * mm * 0.66))
def tbl(rows, widths, hl=None):
    data = [[Paragraph(str(c), ss["th"] if i == 0 else ss["tc"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), INK), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG]),
          ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dee2e6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for r in (hl or []): st.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fff4e6")))
    t.setStyle(TableStyle(st)); story.append(t); story.append(Spacer(1, 6))

def page(c, d):
    c.saveState(); c.setFont("D", 7); c.setFillColor(MUT)
    c.drawString(18 * mm, 10 * mm, "DigitalHeat · Useful Load ⇒ Useful Heat · team technical briefing · sprintd Basel GreenTech 2026")
    c.drawRightString(192 * mm, 10 * mm, str(d.page)); c.restoreState()

# ---------------------------------------------------------------- cover
story += [Spacer(1, 30 * mm), Paragraph("Useful Load ⇒ Useful Heat", ss["t"]),
          Paragraph("Technical briefing on the DigitalHeat case: physics, data, the core problem, economics, scheduler design, sovereignty, architecture and pitch strategy", ss["st"]),
          Paragraph("sprintd Basel · GreenTech Edition · FHNW Campus Dreispitz · 20–22 November 2026<br/>Prepared Friday 20 Nov 2026 evening for the team. All reference-house numbers recomputed from the official Open-Meteo 2025 archive; electricity price from ElCom 2026 (IWB, H4).", ss["b"]),
          Spacer(1, 10)]
box("<b>One-paragraph answer.</b> A basement server is an electric heater that earns money. The case is hard because the same machine sells "
    "two products whose demand curves do not match: <b>heat</b> is seasonal and peaky (the reference house needs 12.5 servers for only 29 hours a year "
    "and less than one server all summer) while <b>compute</b> is flat and deadline-driven. Our position: <b>size for base load (3–6 servers, 46–80 % of heat), "
    "let a backup heater shave the peak, and keep the hardware busy all year by moving interruptible work to whichever eligible site needs heat now</b>, "
    "subject to data-access rules (\"Sovereign AI\"). With the case's own formula the break-even compute price is <b>0.226 CHF per server-hour</b> when all heat is used; "
    f"once hardware amortisation is included it rises to <b>≈0.44–0.54 CHF/h</b>, and utilisation (not heat) becomes the decisive variable.")
story.append(Spacer(1, 6))
tbl([["Key figure (reference house, Basel 2025)", "Value", "Source"],
     ["Annual space-heat demand", f"{N['space']:,.0f} kWh", "case formula on Open-Meteo 2025 hourly"],
     ["Hot water", f"{N['hw']:,.0f} kWh (12 kWh/day)", "case"],
     ["Total heat demand", f"{N['total']:,.0f} kWh", "computed"],
     ["Heating days / coldest hour", f"{N['heating_days']} / {N['tmin']} °C", "computed (matches case)"],
     ["Peak hourly demand", f"{N['peak']:.1f} kW (10 kW space + 0.5 kW hot water)", "computed"],
     ["Hours above 12.5-server level (10 kW)", f"{N['hours_above']['12.5']} h/yr", "computed"],
     ["Electricity price", "33.25 Rp/kWh (IWB, H4, 2026, incl. all fees)", "ElCom via energietarife.ch"],
     ["Value of 1 kWh of server heat", "0.133 CHF (price ÷ 2.5)", "case"],
     ["Break-even, heat fully used (case formula)", "0.226 CHF per server-hour", "computed"],
     ], [70, 55, 45])
story.append(PageBreak())

# ---------------------------------------------------------------- contents
h1("Contents")
for i, t in enumerate(["The event and the case brief", "Who DigitalHeat is, and prior art", "Physics and the reference house",
                       "The core problem", "Servers per house", "What servers do in summer", "Economics and break-even",
                       "Workloads: what runs on a heating server", "Scheduler design", "Data sovereignty and privacy",
                       "System architecture and repository", "Demo and pitch strategy", "Where the model breaks (feasibility)",
                       "Open questions for mentors", "Execution plan", "Appendix: formulas, assumptions, sources"], 1):
    p(f"{i}. {t}")
story.append(PageBreak())

# ---------------------------------------------------------------- 1
h1("1. The event and the case brief")
p("sprintd Basel GreenTech is a 36-hour innovation sprint (about 200 builders, teams of up to four, CHF 5,000 prize pool) on Basel-Stadt's net-zero-2037 goal, "
  "run during Global Entrepreneurship Week Basel and powered by BaselTech, Basel Circular and Basel 2037. Two case partners each judge their own case on Sunday "
  "morning; each picks one finalist for the Grand Finale.")
tbl([["Time (CET)", "Milestone"],
     ["Fri 20 Nov 20:30", "Sprint starts (cases allocated 20:20; teams frozen)"],
     ["Sat 21 Nov 09:00–20:00", "Mentors on site; book slots on the platform"],
     ["Sat 21 Nov 15:00–15:30", "Draft submission (\"rough is fine\")"],
     ["Sun 22 Nov 08:30", "Final submission on the platform"],
     ["Sun 22 Nov 09:00–11:30", "Case pitches: 5 min incl. live demo + 3 min Q&A (DigitalHeat room: Pitch 2 · 2.22)"],
     ["Sun 22 Nov 12:00 / 13:00–14:45", "Finalists chosen / Grand Finale"]], [45, 125])
h2("The DigitalHeat case in its own words (condensed)")
p("<b>Problem.</b> Servers turn almost all electricity into heat, which is normally cooled away with yet more energy; homes meanwhile pay to make heat. "
  "Open questions: which workloads fit, how to schedule them against a home's heat demand across the year, and when it pays off.")
p("<b>Expected outcome.</b> A working demonstrator that schedules interruptible jobs across distributed servers so heat arrives where and when homes need it, "
  "over a full year, with transparent and reproducible numbers on useful heat, useful compute and cost.")
h2("Must-haves (all on the reference house)")
tbl([["#", "Requirement", "What it means in practice"],
     ["1", "Workloads", "≥2 job types with runtime, energy/job, interruptible?, deadline. ≥1 actually runs on our machine with measured runtime; energy from a software meter or runtime × device power; explicit scaling to the 1 kW reference server; jobs/day with a source (an unlimited-backlog model must say so)."],
     ["2", "Scheduling", "Distribute / pause / reschedule by heat demand (winter heating, summer hot water) with a heat tank and a defined fate for jobs whose heat is not needed. The SAME scheduler code that produces the yearly balance must also pause/resume (or checkpoint/restart) a real running process on the heat signal."],
     ["3", "Yearly balance", "Servers/house; share of total heat covered (rest = backup heater); heat dumped; utilisation = running hours ÷ (servers × 8,760); % missed deadlines; electricity cost; compute income; break-even CHF/server-hour = (electricity cost − value of heat used) ÷ server-hours sold; every assumption visible; when it does not pay off."]], [8, 28, 134])
h2("Judging")
tbl([["Criterion", "Weight", "What earns points"],
     ["Transparency & reproducibility", "25 %", "Every number traceable and repeatable; assumptions visible"],
     ["Feasibility", "25 %", "Usable for a pilot decision; knows where assumptions stop holding; states when it does not pay off"],
     ["Scheduling quality & impact", "20 %", "First heat covered at least heat dumped, then utilisation, then missed deadlines"],
     ["Creativity & innovation", "20 %", "Fresh, practical idea for matching compute to heat"],
     ["Design & usability", "10 %", "A homeowner or utility understands the result in one minute"]], [50, 18, 102])
sm("Not valid: a spreadsheet, slides or a simulation alone; at least one real job must run under the scheduler's control. Out of scope: feeding the district heating grid. "
   "Stretch: \"Prepper\" (solar + compute + storage for self-sufficiency), not scored separately. Prize: dinner with the founders and a chance of project work or an internship.")

# ---------------------------------------------------------------- 2
h1("2. Who DigitalHeat is, and prior art")
p("<b>DigitalHeat</b> (digitalheat.ch) is a pilot-stage offering from <b>Virtual Culture GmbH, Basel</b>. Per its site and case slides: units deliver 5–20 kW of heat "
  "at a target flow temperature of 50–70 °C using direct liquid cooling at the processors and a heat exchanger into the building's hot water and space heating; "
  "up to 40 servers per rack; heat is sold as a service (the building owns no hardware); compute customers buy CPU/GPU capacity for AI, data and hosting, "
  "with <b>Swiss data location</b> as the selling point. The deck's title is <b>\"Server heat and Sovereign AI\"</b>, and its scheduling slide lists three control verbs: "
  "<b>slow down</b> (fewer workers / lower clocks), <b>pause and resume</b> (save progress, no repeated work) and <b>distribute</b> (move saved work or next batch to "
  "another <i>eligible</i> site, respecting access and deadlines). The deck's map animation zooms House → Basel → Northwestern Switzerland → Switzerland: the long-term "
  "vision is a national distributed fleet.")
h2("Prior art the jury will know")
tbl([["Who", "Where", "Model", "Lesson for us"],
     ["IWB + Neutral-IT (2020)", "Basel", "Oil-immersed servers in an 80-year-old six-flat building; ~33 MWh heat/yr; 75 % gas reduction target; gas boiler for cold snaps; needs fibre; Neutral-IT routes jobs to where heat is needed", "Same city, same idea; peak backup was already part of the design"],
     ["Qarnot", "France, Finland", "Computing heaters, then boiler modules (up to 12 OCP servers); banks and studios rent the compute", "Revenue from compute buyers, not homeowners"],
     ["Heata", "UK", "Server on the home hot-water cylinder; workloads routed to homes", "Hot water is the year-round anchor load"],
     ["Deep Green", "UK", "Small data centres heating public swimming pools; provider pays electricity", "Pools are ideal summer sinks"],
     ["DigHeat (Dalkia/EDF + Tresorio)", "France", "Servers on customer premises heating domestic hot water; HPC sold as a service", "Utility-led channel"],
     ["Cloud&Heat", "Germany", "Decentralised servers in buildings feeding the heating loop", "Earlier generation; scale and ops cost were the hard parts"],
     ["Infomaniak, Green/Energie 360°", "Geneva, Zurich", "Large data centres feeding district heating", "Centralised alternative (out of scope here)"]], [32, 20, 70, 48])
sm("Industry name for the concept: \"digital boiler\" / \"data furnace\"; Microsoft Research's 2011 Data Furnace paper is the classic reference for the economics.")

# ---------------------------------------------------------------- 3
story.append(PageBreak())
h1("3. Physics and the reference house")
p("Every team uses the same reference house so results are comparable. We recomputed it and match the case exactly.")
code("space_heat_kW(h) = max(0, 10 × (20 − T_h) / 25.6)   on heating days, else 0\n"
     "heating day      = local calendar day with mean of 24 hourly T < 12 °C\n"
     "hot_water_kW     = 12 kWh/day ÷ 24 = 0.5 kW (flat, all year)\n"
     "server           = 1 kW electric → 0.8 kW recoverable heat (19.2 kWh/day)\n"
     "tank             = 35 kWh usable (1,000 L × 30 K), lossless\n"
     "heat value       = electricity price / 2.5   (replaces a heat pump with COP 2.5)")
img("f_year.png")
p("The demand is a near-linear function of outdoor temperature (a degree-hour model) clipped at zero and gated by the heating-day rule. "
  "Note the gate creates <b>discontinuities</b>: a cold night in a warm-mean day gets no space heat. The scheduler must use the same gate or it will "
  "\"cover\" demand that the reference model says does not exist.")
img("f_month.png")
img("f_ldc.png")
p(f"The load-duration curve is the single most important picture of the case. Demand exceeds one server's output (0.8 kW) for {N['hours_above']['1']:,} h, "
  f"four servers' (3.2 kW) for {N['hours_above']['4']:,} h, eight servers' for {N['hours_above']['8']:,} h, ten servers' for {N['hours_above']['10']} h and the "
  f"design peak for only {N['hours_above']['12.5']} h. Classic heating engineering sizes the base-load generator well below peak and lets a cheap peaker cover the tail; "
  "the case explicitly allows this (\"the rest coming from a backup heater outside the model\").")
h2("What the tank can and cannot do")
p("35 kWh is ~3.5 h of the 10 kW peak, or ~3 days of summer hot water. It smooths <b>intra-day</b> mismatch (charge at night or during compute bursts, discharge "
  "in the morning peak) and lets jobs keep running for hours after demand drops, but it is <b>irrelevant to the seasonal</b> mismatch (~31 MWh winter vs. ~4 MWh summer).")

# ---------------------------------------------------------------- 4
story.append(PageBreak())
h1("4. The core problem")
box("<b>One machine, two products, mismatched demand.</b> Heat demand is seasonal, weather-driven and peaky. Compute demand is flat, deadline-driven and "
    "price-sensitive. A heating server only creates value when <i>both</i> exist at the same place and time. Every design decision is a choice of who absorbs the mismatch: "
    "the compute customer (pauses, delays, missed deadlines), the heat customer (backup heater), the operator (idle or dumping hardware) or another site (migration).")
h2("Three sub-problems")
bl(["<b>Sizing.</b> Enough servers for winter means idle servers in summer; too few and the backup heater does most of the heating, weakening the product.",
    "<b>Flexibility allocation.</b> The scheduler decides, hour by hour, whether to run (useful heat + income), pause (no heat, no income, deadline risk), dump (income, wasted heat) or migrate (income, heat elsewhere, data movement).",
    "<b>Economics.</b> Compute must sell above (electricity − heat value) per hour, plus hardware amortisation that the case formula omits, and still beat cloud spot prices; that only works at high utilisation."])
h2("Why this is not just a heating problem")
p("Data centres pay to remove heat (PUE overhead); homes pay to make it. The value proposition is the <b>avoided cooling + avoided heating</b>. "
  "But the heat value is small compared with electricity: 0.8 kWh of heat is worth 0.8 × 33.25/2.5 = 10.6 Rp, about a third of the 33.25 Rp electricity bill for that hour, "
  "because the competitor is a heat pump (COP 2.5), not resistive heating. So heat <b>subsidises</b> compute by ~32 %; it does not pay for it.")

# ---------------------------------------------------------------- 5
h1("5. Servers per house")
p("We simulated all 8,760 hours for 1–13 servers under two policies: <b>heat-following</b> (servers run only to meet demand and fill the tank; never dump) and "
  "<b>always-on</b> (all servers run 24/7; surplus beyond the tank is dumped).")
img("f_tradeoff.png")
story.append(Table([[Image("f_jan.png", width=84 * mm, height=55 * mm), Image("f_jul.png", width=84 * mm, height=55 * mm)]]))
sm("Four servers, heat-following. Left: the coldest day of 2025 (31 Dec) — servers run flat out and the backup heater covers the gap. Right: a July day — "
   "one server-equivalent runs in short bursts to keep the tank topped up for hot water; the other three are idle unless work migrates elsewhere.")
rows = [["N", "Heat covered", "Utilisation (heat-following)", "Heat dumped if always-on", "Break-even (case formula, always-on)", "Break-even + hardware (heat-following / always-on)"]]
for f, a in zip(FO, AL):
    rows.append([int(f["N"]), f"{100*f['covered']:.0f} %", f"{100*f['util']:.0f} %", f"{a['dump']:,.0f} kWh", f"{a['be']:.3f}", f"{f['be_capex']:.3f} / {a['be_capex']:.3f}"])
tbl(rows, [16, 22, 32, 30, 32, 38], hl=[3, 4, 5, 6])
sm("Hardware assumption: CHF 8,000 per 1 kW server incl. liquid cooling and installation, 5-year straight-line, no residual value, no cost of capital. "
   "Heat-following break-even with the case formula is constant at 0.226 CHF/h because every heat-following server-hour delivers useful heat.")
box("<b>Recommendation: 4 servers per house (58 % coverage, 65 % utilisation) as the headline, with a sweep 1–13 in the dashboard.</b> "
    "3–6 is the defensible band. Above ~6 each server adds little heat (the 7th adds 7.5 pp, the 10th 2.4 pp) but a full server of idle capex.")

# ---------------------------------------------------------------- 6
story.append(PageBreak())
h1("6. What servers do in summer")
p("From April to September (outside heating days) the house needs 0.5 kW, less than one server. Options, roughly from weakest to strongest:")
tbl([["Strategy", "Effect", "Verdict"],
     ["Pause / throttle (slow-down verb)", "No dumping; utilisation collapses; capex idle", "Necessary fallback, not a business"],
     ["Run anyway and dump heat", "Utilisation stays high; becomes a tiny inefficient data centre with no PUE advantage", "Only if compute price > ~0.33 CHF/h electricity + capex"],
     ["Seasonal job mix", "Bulk batch work (embeddings, re-indexing, evaluation, rendering) in winter; only urgent high-value jobs in summer", "Good; shapes demand, needs a scheduler with deadlines"],
     ["Migrate to year-round heat sinks", "Hotels, spas, pools, laundries, care homes, greenhouses, dairies and businesses with process heat get the summer work", "Strongest: the slide's \"another eligible site\""],
     ["Pre-heat the tank with solar-powered compute (Prepper)", "PV midday surplus runs compute; tank stores heat for evening showers", "Nice stretch; good self-sufficiency story"],
     ["Physically move racks seasonally", "Install in homes Oct–Mar, in summer sinks Apr–Sep", "Creative, but labour and downtime"]], [48, 82, 40])
h2("The portfolio view (our core idea)")
p("Treat the fleet, not the house, as the unit of utilisation. A Basel portfolio of N homes plus a few year-round sites lets each server stay busy because "
  "<i>somewhere</i> needs heat. In the limit (enough summer sinks) every server-hour is both sold and useful, so break-even falls to the case value 0.226 CHF/h plus "
  "hardware at ~100 % utilisation: 0.226 + 8,000/(5 × 8,760) = <b>0.41 CHF/h</b>. That is the target the scheduler is optimising towards. "
  "The live demo shows it on a small scale: work migrates between \"houses\" (laptops) as the heat signal moves.")

# ---------------------------------------------------------------- 7
h1("7. Economics and break-even")
code("electricity_cost = Σ_server-hours × 1 kW × 0.3325 CHF/kWh\n"
     "heat_value       = heat_actually_used_kWh × 0.3325 / 2.5\n"
     "break_even       = (electricity_cost − heat_value) / server_hours_sold          (case)\n"
     "break_even_hw    = break_even + capex_per_server / (life_years × 8,760 × utilisation)   (ours)")
img("f_breakeven.png")
p("<b>The counter-intuitive result.</b> Under the case formula heat-following always wins (it never wastes heat). Once hardware is included, "
  "<b>always-on wins</b> for every house size, because idle hardware is more expensive than wasted heat: at 4 servers, heat-following costs 0.509 CHF/h vs. 0.446 for always-on. "
  "The best of both is the portfolio: heat-following <i>per site</i>, always-on <i>per fleet</i>.")
h2("Is 0.23–0.50 CHF per server-hour competitive?")
p("Indicative public cloud list prices (verify on the day; they change often): server-class x86 vCPU on demand ≈ 0.04–0.05 USD per vCPU-hour, spot 50–70 % cheaper; "
  "a single mid-range inference GPU instance (L4/A10 class) ≈ 0.7–1.2 USD/h on demand. A 1 kW reference server is roughly a dual-socket CPU node (~100+ vCPU) or a 1–2 GPU "
  "node, so its cloud-equivalent value is in the order of <b>1–5 CHF per hour</b> on demand and well above 0.4 CHF/h even at spot prices. "
  "The compute side is therefore not the binding constraint; <b>finding enough interruptible demand that tolerates pauses, and trusting the sites with data</b>, is.")
sm("Pricing comparison is an order-of-magnitude argument for the pitch; teams must source the exact instance prices they quote (AWS/Azure/GCP pricing pages).")
h2("When it does NOT pay off (state this on stage)")
bl(["Electricity above ~0.55 CHF/kWh with spot-level compute prices.",
    "Utilisation below ~40 % per server (oversized houses, no summer sinks).",
    "Workloads with hard real-time SLAs or large data transfer per job (rural uplinks, egress costs).",
    "Hardware costs above ~CHF 15k per kW or lifetimes below 3 years (GPU obsolescence).",
    "Sites without fibre, or customers whose data may not leave a certified facility."])

# ---------------------------------------------------------------- 8
story.append(PageBreak())
h1("8. Workloads: what runs on a heating server")
tbl([["Job type", "Interruptible?", "Checkpoint granularity", "Typical deadline", "Fit"],
     ["Text embeddings / document indexing (sentence-transformers)", "Yes", "per batch (e.g. 256 docs)", "hours–days", "Excellent; CPU-friendly, trivially resumable"],
     ["Speech transcription (Whisper / faster-whisper)", "Yes", "per audio segment (~30 s)", "minutes–hours", "Very good; visible progress for demo"],
     ["Image tagging / CLIP embeddings / visual search", "Yes", "per image batch", "hours", "Very good"],
     ["Batch LLM inference / model evaluation", "Yes", "per prompt batch", "hours–days", "Good (GPU); sovereignty selling point"],
     ["Rendering, simulations, Monte Carlo", "Yes", "per frame / per sample block", "hours–days", "Good, classic for Qarnot"],
     ["Model training / fine-tuning", "Partly", "per step (large state)", "days", "OK; big checkpoints make migration costly"],
     ["Interactive inference / web hosting", "No", "—", "milliseconds", "Poor; needs always-on capacity elsewhere"]], [45, 18, 32, 25, 50])
h2("Measurement and scaling to the 1 kW server (must-have 1)")
bl(["Run the job on a laptop with a fixed batch; record wall time and energy. Linux: RAPL counters (/sys/class/powercap/intel-rapl*/energy_uj) or codecarbon; macOS: powermetrics (sudo) or declared package power.",
    "Express as <b>work per kWh</b> (e.g. embeddings/kWh, audio-minutes/kWh). Scale to the reference server with a stated factor: e.g. MLPerf Inference datacenter results report throughput and system power, giving samples/s/W for comparable models; assume the 1 kW server delivers <i>k</i> × the laptop's work/kWh and give a range.",
    "Derive runtime per job on the reference server = job_size / (server work rate); energy per job = runtime × 1 kW.",
    "Jobs per day: from the Alibaba PAI GPU trace (6,500 GPUs, Jul–Aug 2020; job durations, arrivals, resource requests) as an arrival-rate shape, scaled to a Basel customer base; or an explicit assumption (\"N customers × M jobs\"). Never silently assume an infinite backlog."])
h2("Pausing a real process (must-have 2)")
tbl([["Mechanism", "How", "Pros", "Cons"],
     ["SIGSTOP / SIGCONT", "os.kill(pid, SIGSTOP)", "Instant; zero code changes; shows state \"T\" in ps", "Memory stays allocated; cannot migrate"],
     ["Cooperative checkpoint", "SIGTERM handler writes progress (batch index, partial outputs) and exits; restart reads it", "Migratable; no repeated work; survives reboot", "Needs job code support"],
     ["Throttle", "fewer worker threads, taskset/cpulimit, lower batch size", "Matches the slide's slow-down verb; partial heat", "Less dramatic for demo"],
     ["Container checkpoint (CRIU / Podman)", "checkpoint the whole container", "Generic", "Linux-only, fragile on laptops; skip for hackathon"]], [32, 50, 44, 44])

# ---------------------------------------------------------------- 9
story.append(PageBreak())
h1("9. Scheduler design")
p("One pure function decides; two drivers call it (the 8,760-h simulator and the live coordinator). This satisfies \"same scheduler code\" literally.")
code("decide(sites: [SiteState], queue: [Job], hour) -> [Action]\n"
     "SiteState = {site_id, demand_kW, tank_kWh, tank_cap, servers, eligible_classes, forecast_kW[24]}\n"
     "Job       = {id, type, remaining_h, deadline, access_class, interruptible, price}\n"
     "Action    = Run(job, site) | Pause(job) | Migrate(job, site) | Dump(site, kWh) | Idle(site, n)")
h2("Policy layers (build in this order)")
bl(["<b>L0 heat-following greedy.</b> Servers to run at a site = ceil((demand + tank headroom)/0.8), capped at servers. Fill them with jobs by earliest deadline (EDF); pause the rest.",
    "<b>L1 deadline guard.</b> If a job's slack (deadline − now − remaining) drops below a threshold, run it even if the heat is dumped (or migrate it); count the dumped kWh as the cost of the SLA.",
    "<b>L2 migration.</b> If a site has no heat need and another eligible site does, migrate the job (checkpoint transfer cost modelled as a few minutes of lost compute).",
    "<b>L3 forecast / MPC.</b> Use the next 24 h of temperatures (perfect forecast from the archive, or noise-added) to pre-charge the tank before morning peaks and to release batch jobs ahead of cold nights. A small linear program (or greedy rolling horizon) over the 24 h window is enough.",
    "<b>L4 price-aware (optional).</b> Shift dumpable work to low-price or low-carbon hours; not required by the case."])
h2("Metrics the scheduler optimises (jury order)")
p("1) share of heat demand covered at the least heat dumped; 2) utilisation; 3) missed deadlines. We expose a single weighted objective for tuning but always report all three.")
h2("Scenario set for the yearly balance")
tbl([["Scenario", "Sites", "Purpose"],
     ["A. Reference house alone, heat-following", "1 house", "Required baseline; maximum heat efficiency"],
     ["B. Reference house always-on", "1 house", "Shows dumping and the hardware trade-off"],
     ["C. Portfolio", "k houses + 1–2 year-round sinks", "Our core idea; utilisation near 100 %"],
     ["D. Sovereignty constraint", "as C, with 30 % swiss-only / 10 % certified jobs", "Cost of the access rule in heat and deadlines"],
     ["E. Sensitivities", "price ±30 %, capex 5–15k, tank 0–70 kWh, N 1–13", "Where it stops paying off"]], [55, 50, 65])

# ---------------------------------------------------------------- 10
h1("10. Data sovereignty and privacy")
p("The case text never says \"privacy\", but the deck's title (\"Sovereign AI\"), \"local data and operations\" and the scheduling rule \"distribute to another <i>eligible</i> site, respecting access\" "
  "make it a first-class constraint. Servers sit in other people's basements; migration moves customer data between homes over residential links.")
tbl([["Threat", "Mitigation"],
     ["Physical access to disks or memory by occupants or technicians", "Full-disk encryption; keys released remotely only after attestation; tamper switch wipes keys; sealed chassis"],
     ["Data in transit during migration", "mTLS between nodes; encrypted checkpoints; no plaintext on shared Wi-Fi"],
     ["Checkpoint residue", "Encrypt checkpoints with per-job keys; secure delete on completion"],
     ["Model or IP theft", "Confidential computing (Intel TDX, AMD SEV-SNP, NVIDIA confidential GPUs) for certified sites"],
     ["Compliance (Swiss revFADP, GDPR)", "Access classes: public / swiss-only / certified; site eligibility list; audit log of where each job ran"],
     ["Sensitive inputs (audio, documents)", "Pre-processing to strip identifiers; route sensitive classes only to certified sites"]], [60, 110])
box("<b>In our build:</b> every job has <font name='DM'>access_class</font> and every site an <font name='DM'>eligible_classes</font> set. The scheduler never places a job on an ineligible site; "
    "the live agent returns HTTP 403 if asked to. Scenario D quantifies the cost of the rule (lost coverage, extra dumping, delayed jobs), turning privacy into a number the jury can weigh.")

# ---------------------------------------------------------------- 11
story.append(PageBreak())
h1("11. System architecture and repository")
code("data/raw/basel_2025_hourly.csv ─► house_model ─► simulate_year ─► runs/<id>/balance.json, hourly.parquet, sweep.csv ─► dashboard\n"
     "                                       ▲                                                                                │\n"
     "jobs (catalogue, arrivals, runner) ─────┴─► scheduler.decide()  ◄── live_agent.coordinator ─► nodes (FastAPI :8710) ◄──┘\n"
     "                                                                       pause/resume/checkpoint/migrate real processes")
p("Repository: <font name='DM'>github.com/Mulaydm10/sprintd-basel-greentech-digitalheat</font> (private). Coordination uses the agent-bus protocol: each "
  "<font name='DM'>src/&lt;package&gt;</font> is a lane, each task an issue, each claim a <font name='DM'>claim/&lt;n&gt;</font> branch; the design session (Claude on the Omen) "
  "is the only writer of <font name='DM'>main</font>. Contracts in <font name='DM'>contracts/src/*.md</font> fix the interfaces so lanes can be built in parallel.")
tbl([["Issue", "Lane", "Prio", "Deliverable"],
     ["#4", "src/house_model", "p0", "reference profile (8,760 rows) + Tank; tests pin 26,851 kWh, 206 days, −5.6 °C"],
     ["#5", "src/jobs", "p0", "≥2 job types, one measured; resumable runner (SIGTERM→checkpoint, SIGSTOP/CONT safe)"],
     ["#6", "src/scheduler", "p0", "pure decide() with access classes and determinism"],
     ["#7", "src/simulate_year", "p1", "8,760-h balance.json with all must-have keys + sweep"],
     ["#8", "src/live_agent", "p1", "per-node FastAPI: start/pause/resume/checkpoint/migrate, 403 on ineligible"],
     ["#9", "src/dashboard", "p2", "key figures, Jan/Jul replay, live nodes"]], [14, 30, 12, 114])

# ---------------------------------------------------------------- 12
h1("12. Demo and pitch strategy")
h2("Five-minute pitch (DEMO.md is the source of truth)")
tbl([["Time", "Content"],
     ["0:00–0:45", "Key figures first: servers/house, heat covered, heat dumped, utilisation, missed deadlines, break-even CHF/server-h (case formula and with hardware)"],
     ["0:45–1:30", "The core insight in one chart: load-duration curve and the coverage/utilisation trade-off; why 4 servers and a backup"],
     ["1:30–3:30", "Live demo: replay a January night (all nodes run), the tank fills at midday (lower-priority job pauses), migrate a running transcription to the \"hotel\" node which resumes at the same timestamp; a swiss-only job refuses the ineligible node and the dashboard prices the rule"],
     ["3:30–4:30", "July day and the portfolio: where summer work goes; break-even falls to ~0.41 CHF/h at fleet utilisation"],
     ["4:30–5:00", "When it does not pay off, and what DigitalHeat should pilot next"]], [22, 148])
box("<b>The wow moment.</b> Several real machines on the table act as houses. A transcription of <i>our own pitch</i> runs on one laptop; the heat signal says that house is warm; "
    "the job checkpoints, travels and resumes mid-sentence on another machine. A confidential job is refused by an ineligible site. All of it is driven by the same "
    "<font name='DM'>decide()</font> that produced the yearly numbers.")
h2("Rubric mapping")
tbl([["Criterion", "Our evidence"],
     ["Transparency 25", "assumptions.yaml single source; every number in balance.json reproducible with one command; EXP rows for measurements; notebook for charts"],
     ["Feasibility 25", "Break-even with and without hardware; explicit \"does not pay off\" envelope; sizing for base load like real heating engineering; prior art"],
     ["Scheduling 20", "Coverage at zero dump (heat-following) vs. utilisation (portfolio); deadline guard; migration"],
     ["Creativity 20", "Fleet-level utilisation, access-class sovereignty with priced cost, live migration of a real job"],
     ["Design 10", "One-screen dashboard: a homeowner reads \"58 % of your heat, CHF x saved\" in a minute"]], [35, 135])

# ---------------------------------------------------------------- 13
story.append(PageBreak())
h1("13. Where the model breaks (say it before the jury does)")
bl(["<b>Flow temperature.</b> The case assumes recovered heat serves space heating and hot water without a heat pump. Hot water needs ~55–60 °C for legionella safety; direct liquid cooling at 50–70 °C is plausible but leaves little margin, and many older radiator systems need 55–70 °C on cold days.",
    "<b>Heat value.</b> Valuing heat against a COP-2.5 heat pump is conservative for oil/gas-heated buildings (heat worth more, CO<sub>2</sub> saving larger) and generous against a modern COP-4 heat pump.",
    "<b>Hardware omitted.</b> The case break-even ignores capex, maintenance, connectivity (fibre), insurance and site rent; we add capex explicitly.",
    "<b>Network.</b> Residential uplinks limit data-heavy jobs; checkpoint sizes matter for migration.",
    "<b>Noise, space, safety.</b> 4–12 kW of servers in a basement needs ventilation for the 20 % unrecovered heat, fire safety and noise control.",
    "<b>Demand certainty.</b> Revenue depends on a steady supply of interruptible jobs at a price; the model must show sensitivity to jobs/day.",
    "<b>Reference-model artefacts.</b> The heating-day gate and lossless tank make the numbers cleaner than reality; report it."])

h1("14. Open questions for mentors and DigitalHeat")
bl(["Draft submission format on Saturday 15:00: link to repo, a short text, or a video?",
    "Are pre-existing open-source models and AI-written code fine (we assume yes, with attribution)?",
    "Does DigitalHeat want hardware cost in the break-even, or strictly the case formula plus an optional extension?",
    "Their real server spec (CPU/GPU, kW per node) to calibrate the scaling factor; any measured flow temperatures?",
    "Which customer workloads have they actually seen or been asked for?",
    "Is \"another eligible site\" already a business plan (hotels, spas) or an open idea?"])

h1("15. Execution plan (to Sunday 08:30)")
tbl([["When (CET)", "Gate", "Done when"],
     ["Fri night", "G0 foundations", "profile CSV + house_model tests green; one embedding job measured on a laptop; decide() L0"],
     ["Sat 09:00–13:00", "G1 yearly balance", "simulate_year writes balance.json for N=1..13; first key figures"],
     ["Sat 15:00", "Draft submission", "repo + key figures + one paused/resumed real process"],
     ["Sat afternoon", "G2 live", "live_agent on 2 machines, migrate + resume; access-class refusal"],
     ["Sat evening", "G3 dashboard + portfolio", "dashboard, scenarios C/D/E, charts"],
     ["Sun 07:00", "G4 freeze", "rehearse DEMO.md twice with the reset procedure; final submission 08:30"]], [30, 40, 100])

# ---------------------------------------------------------------- appendix
story.append(PageBreak())
h1("Appendix A. Assumptions used in this briefing")
tbl([["Parameter", "Value", "Source / status"],
     ["Weather", "Open-Meteo archive, Basel 47.56 N 7.59 E, 2025 hourly, Europe/Zurich", "case; recomputed"],
     ["Space-heat formula, heating-day rule, 25.6 constant", "as case", "case"],
     ["Hot water", "12 kWh/day", "case"],
     ["Tank", "35 kWh, lossless", "case"],
     ["Server", "1 kW in, 0.8 kW recoverable", "case"],
     ["Electricity price", "0.3325 CHF/kWh (IWB H4 2026 total)", "ElCom data via energietarife.ch; 2025 was 33.86 Rp"],
     ["Heat value", "price / 2.5", "case"],
     ["Hardware", "CHF 8,000 per server, 5 years, no residual", "our assumption; sweep 5–15k"],
     ["Heat-following policy", "run only for demand + tank headroom, never dump", "ours"],
     ["Always-on policy", "all servers 24/7, dump beyond tank", "ours"],
     ["Cloud prices", "order-of-magnitude only", "to be sourced exactly before quoting"]], [55, 65, 50])
h1("Appendix B. Simulation pseudo-code")
code("for each hour h:\n"
     "    take = min(tank, demand[h]);  tank -= take;  rest = demand[h] - take\n"
     "    heat = 0.8 * servers_running(h)          # policy decides servers_running\n"
     "    used = min(heat, rest);  excess = heat - used\n"
     "    charge = min(excess, TANK_CAP - tank);  tank += charge;  dumped += excess - charge\n"
     "    covered += take + used;  run_hours += servers_running(h)\n"
     "share_covered = covered / Σdemand;  utilisation = run_hours / (servers × 8760)")
h1("Appendix C. Sources")
for s in ["sprintd platform, case page \"Useful Load ⇒ Useful Heat\" and DigitalHeat case slides (DigitalHeat.pdf), 20 Nov 2026",
          "Open-Meteo Historical Weather API, archive-api.open-meteo.com (Basel 2025 hourly)",
          "ElCom tariff data via energietarife.ch: IWB Industrielle Werke Basel, H4, 2026 total 33.25 Rp/kWh (2025: 33.86)",
          "digitalheat.ch (Virtual Culture GmbH, Basel): product description, 5–20 kW, 50–70 °C",
          "IWB press release, 18 June 2020: Mini-Rechenzentren heizen Basler Wohnungen; SRF, 3 July 2020: Computer heizt Basler Mehrfamilienhaus",
          "MLCommons MLPerf Inference datacenter results with power: mlcommons.org/benchmarks/inference-datacenter",
          "Alibaba cluster-trace-gpu-v2020 (PAI, 6,500 GPUs, Jul–Aug 2020): github.com/alibaba/clusterdata; Weng et al., NSDI '22",
          "TechCrunch (Qarnot, 2023); MIT Technology Review (Heata, 2023); DCD (Deep Green, 2023); electricdays.fr (DigHeat)",
          "Liu et al., \"The Data Furnace: Heating Up with Cloud Computing\", HotCloud 2011"]:
    sm("• " + s)

doc = BaseDocTemplate("DigitalHeat_Technical_Briefing.pdf", pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                      title="DigitalHeat — Technical Briefing", author="sprintd Basel team")
doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(18 * mm, 16 * mm, 174 * mm, 263 * mm, id="f")], onPage=page)])
doc.build(story)
print("ok")
