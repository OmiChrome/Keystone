"""Generate the synthetic sample projects (PDFs + CSVs + ground-truth labels).

All companies, products and model numbers in these files are FICTIONAL and exist only to exercise the
agents. Technical values (ratings, standards such as UL 1558, ANSI C12.20, NEC 240.87, AHRI 550/590)
are realistic for the equipment class. Ground-truth labels were written by hand alongside the documents.

Project Alpha  - 480 V switchgear package for a data-center build (development set)
Project Beta   - air-cooled chiller package (HELD-OUT set: never used while writing prompts)

Usage: uv run python samples/generate.py
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
ss = getSampleStyleSheet()
H1, H2, BODY = ss["Heading1"], ss["Heading3"], ss["BodyText"]


def pdf(path: Path, blocks: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    story = []
    for b in blocks:
        if b == "PAGE":
            story.append(PageBreak())
        elif isinstance(b, tuple) and b[0] == "h1":
            story.append(Paragraph(b[1], H1))
        elif isinstance(b, tuple) and b[0] == "h2":
            story.append(Paragraph(b[1], H2))
        elif isinstance(b, tuple) and b[0] == "table":
            t = Table(b[1], hAlign="LEFT", colWidths=b[2] if len(b) > 2 else None)
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 8))
        else:
            story.append(Paragraph(b, BODY))
            story.append(Spacer(1, 3))
    SimpleDocTemplate(str(path), pagesize=LETTER, leftMargin=0.8 * inch, rightMargin=0.8 * inch).build(story)


def money(v: float) -> str:
    return f"${v:,.0f}"


# =============================================================================== PROJECT ALPHA

ALPHA = HERE / "project_alpha"

alpha_spec = [
    ("h1", "SECTION 26 23 00 - LOW-VOLTAGE SWITCHGEAR"),
    "Project Alpha - Data Center Building DC-1, Electrical Room ER-1. Issued for Construction, Rev 2.",
    ("h2", "PART 1 - GENERAL"),
    "1.1 SUMMARY. A. Section includes metal-enclosed, drawout low-voltage power circuit breaker switchgear SWG-1 serving the UPS and mechanical loads.",
    "1.2 SUBMITTALS. A. Product data, shop drawings with dimensions, short-circuit ratings, seismic certificates and factory test reports.",
    "1.5 WARRANTY. A. Manufacturer's warranty shall cover parts and labor for not less than 24 months from the date of Substantial Completion.",
    "1.6 DELIVERY. A. Switchgear shall be delivered to site not later than 30 weeks after receipt of approved submittals.",
    ("h2", "PART 2 - PRODUCTS"),
    "2.1 BASIS OF DESIGN. A. Manufacturers' standard products meeting every requirement of this Section. Substitutions per Section 01 25 00.",
    "2.2 RATINGS. A. System voltage: 480Y/277 V, 3-phase, 4-wire, 60 Hz.",
    "2.2.B Main horizontal bus continuous current rating shall be not less than 4000 A.",
    "2.2.C Short-circuit current rating shall be not less than 65 kA RMS symmetrical at 480 V. Equipment shall be fully rated; series ratings are not acceptable.",
    "2.3 CONSTRUCTION. A. Bus: silver-plated copper throughout, including main, riser and neutral bus.",
    "2.3.B Neutral bus shall be 100 percent rated.",
    "2.3.C Ground bus: copper, extending the full length of the lineup.",
    "2.3.D Enclosure: NEMA 1 indoor, UL 1558 listed and labeled.",
    "2.3.E The overall lineup length shall not exceed 240 inches to fit Electrical Room ER-1.",
    "2.3.F Finish: ANSI 61 light gray, manufacturer's standard powder coat.",
    "PAGE",
    "2.4 CIRCUIT BREAKERS. A. Drawout, electrically operated low-voltage power circuit breakers listed to UL 1066.",
    "2.4.B Trip units: microprocessor-based with long-time, short-time, instantaneous and ground-fault (LSIG) functions.",
    "2.4.C Arc energy reduction: provide an energy-reducing maintenance switch per NEC 240.87 on every breaker rated 1200 A or higher.",
    "2.5 METERING AND COMMUNICATIONS. A. Main power meter shall be revenue-grade, accuracy class 0.2 per ANSI C12.20.",
    "2.5.B Communications: native Modbus TCP and BACnet/IP to the Electrical Power Monitoring System.",
    "2.6 SURGE PROTECTION. A. Integral surge protective device listed to UL 1449 4th Edition, with surge current rating of not less than 200 kA per phase.",
    "2.7 SEISMIC. A. Switchgear shall be seismically qualified per IBC 2021 and ICC-ES AC156 for the project site (SDS = 1.0 g), with certificate of compliance.",
    ("h2", "PART 3 - EXECUTION"),
    "3.2 FIELD QUALITY CONTROL. A. Factory witness testing: provide factory witness testing for up to two Owner representatives prior to shipment.",
    "3.3 STARTUP. A. Manufacturer's field service engineer shall perform startup, testing and commissioning support.",
    "END OF SECTION 26 23 00",
]

alpha_submittal = [
    ("h1", "SUBMITTAL 26 23 00-01 - LV SWITCHGEAR SWG-1"),
    "Submitted by: Voltara Power Systems Pvt. Ltd. (fictional) | Project: Project Alpha, DC-1 | Product line: VPS-LV5000 (fictional)",
    ("h2", "1. Product Data - Electrical Ratings"),
    (
        "table",
        [
            ["Parameter", "Offered"],
            ["System", "480Y/277 V, 3 phase, 4 wire, 60 Hz"],
            ["Main bus continuous rating", "4000 A"],
            ["Short-circuit current rating", "50 kA RMS symmetrical at 480 V (fully rated)"],
            ["Bus material", "Tin-plated copper (main, riser and neutral)"],
            ["Neutral bus", "100% rated"],
            ["Ground bus", "Copper, full length of lineup"],
            ["Enclosure", "NEMA 1 indoor, UL 1558 listed"],
            ["Finish", "ANSI 61 gray powder coat"],
        ],
        [2.2 * inch, 4.4 * inch],
    ),
    ("h2", "2. Dimensions"),
    "Lineup: 8 vertical sections. Overall lineup length: 6,400 mm. Depth: 1,520 mm. Height: 2,286 mm. See drawing VPS-SWG1-GA-01.",
    ("h2", "3. Circuit Breakers"),
    "VPS-PCB drawout, electrically operated low-voltage power circuit breakers, UL 1066 listed. Trip units: VPS-Trip 900 microprocessor trip unit with LSIG protection on all breakers.",
    "Arc energy reduction: maintenance mode switch with blue indicating light provided on all breakers rated 1200 A and above, in accordance with NEC 240.87.",
    "PAGE",
    ("h2", "4. Metering and Communications"),
    "Main meter: VPS-PM50 power meter, accuracy class 0.5 per ANSI C12.20. Communications: Modbus TCP via Ethernet port. BACnet/IP is available through an optional external gateway (not included in this submittal).",
    ("h2", "5. Surge Protection"),
    "Integral SPD, UL 1449 4th Edition listed, surge current rating 160 kA per phase, mounted in the main incoming section.",
    ("h2", "6. Testing"),
    "Factory witness testing is offered for up to two Owner representatives at the Pune works. Standard production tests per UL 1558 and ANSI C37.51.",
    ("h2", "7. Warranty and Delivery"),
    "Standard warranty: 18 months from date of shipment. Estimated delivery: 34 weeks after approval of submittals, FOB factory.",
]

ALPHA_SCOPE = [
    "Switchgear lineup per Section 26 23 00",
    "Integral surge protective device (SPD)",
    "Revenue-grade power metering",
    "Freight to site (DDP)",
    "Offloading and rigging at site",
    "Startup and commissioning",
    "Factory witness testing",
    "Arc flash and coordination study",
    "Owner training",
    "Spare parts",
    "Seismic certification",
    "24-month warranty",
]


def bid_doc(title, bidder, intro, lines, stated_total, notes, exclusions, quals, lead):
    rows = [["Item", "Description", "Price (USD)"]] + [[str(i + 1), d, money(p)] for i, (d, p) in enumerate(lines)]
    rows.append(["", "TOTAL LUMP SUM BID", money(stated_total)])
    blocks = [("h1", title), f"Bidder: {bidder}", intro, ("h2", "Pricing"), ("table", rows, [0.5 * inch, 4.3 * inch, 1.5 * inch])]
    blocks += [("h2", "Clarifications")] + notes
    blocks += [("h2", "Exclusions")] + (exclusions or ["None."])
    blocks += [("h2", "Qualifications and Commercial Terms")] + quals + [f"Lead time: {lead}"]
    return blocks


alpha_bids = {
    "bid_voltara.pdf": bid_doc(
        "PROPOSAL VPS-Q-2611-044 - LV SWITCHGEAR SWG-1, PROJECT ALPHA",
        "Voltara Power Systems Pvt. Ltd. (fictional)",
        "We are pleased to offer the following for Section 26 23 00 Low-Voltage Switchgear, per drawings E-401 to E-405.",
        [
            ("480 V switchgear lineup SWG-1, 4000 A, 8 sections, per Section 26 23 00", 880000),
            ("Integral SPD, UL 1449 4th Ed.", 38000),
            ("Revenue power metering and communications", 26000),
            ("Factory witness testing, two Owner representatives", 12000),
            ("Arc flash and short-circuit coordination study", 18000),
            ("Owner training, one 8-hour session", 6000),
            ("Recommended spare parts kit", 14000),
        ],
        994000,
        ["Pricing is FOB factory, Pune. Equipment warranty 18 months from shipment."],
        [
            "Freight to jobsite is excluded.",
            "Offloading, rigging and setting in place are excluded.",
            "Startup and commissioning by others.",
        ],
        ["Proposal valid for 60 days. Payment: 20% with order, 70% on shipment, 10% on energization."],
        "34 weeks after approved submittals.",
    ),
    "bid_northgate.pdf": bid_doc(
        "QUOTATION NG-7731 - PROJECT ALPHA 480V SWITCHGEAR",
        "Northgate Electric Manufacturing (fictional)",
        "Northgate is pleased to quote the switchgear package complete per Section 26 23 00 Rev 2.",
        [
            ("Switchgear lineup SWG-1 per specification", 1012000),
            ("Surge protective device, 200 kA per phase", 41000),
            ("Revenue-grade metering, 0.2 class", 29500),
            ("Freight to site, DDP Navi Mumbai", 22000),
            ("Offloading, rigging and setting in place", 16500),
            ("Field startup and commissioning", 31000),
            ("Factory witness test", 11000),
            ("Arc flash and coordination study", 21000),
            ("Owner training (2 sessions)", 7500),
            ("Spare parts", 16000),
            ("Seismic certification (ICC-ES AC156)", 9500),
        ],
        1217000,
        ["Warranty: 24 months from Substantial Completion, parts and labor, included."],
        [],
        [
            "Prices valid 30 days.",
            "Pricing is subject to a copper metals escalation clause indexed to LME copper at the time of release to manufacture.",
        ],
        "40 weeks after approved submittals.",
    ),
    "bid_helix.pdf": bid_doc(
        "BID FORM - HELIX SWITCHGEAR CO. - PROJECT ALPHA SWG-1",
        "Helix Switchgear Co. (fictional)",
        "Helix offers the following lump sum for the low-voltage switchgear.",
        [
            ("LV switchgear lineup SWG-1, 4000 A", 905000),
            ("Power metering", 24500),
            ("Freight DDP to site", 19000),
            ("Offloading and rigging", 14000),
            ("Startup and commissioning", 27000),
            ("Factory witness testing", 10000),
            ("Training", 5000),
        ],
        991500,
        ["Standard warranty 12 months from energization."],
        [
            "Surge protective devices by others.",
            "Arc flash study excluded.",
            "Spare parts are not included.",
            "Seismic certification by others.",
        ],
        ["Validity 45 days."],
        "30 weeks after approved submittals.",
    ),
}

alpha_truth = {
    "compliance": {
        "spec": "spec_26_23_00_lv_switchgear.pdf",
        "submittal": "submittal_voltara_swg1.pdf",
        "labels": {
            "1.5.A warranty 24 months": "deviate",
            "1.6.A delivery 30 weeks": "deviate",
            "2.2.A 480Y/277V 3ph 4w 60Hz": "comply",
            "2.2.B main bus >= 4000 A": "comply",
            "2.2.C SCCR >= 65 kA": "deviate",
            "2.3.A silver-plated copper bus": "deviate",
            "2.3.B neutral 100% rated": "comply",
            "2.3.C copper ground bus full length": "comply",
            "2.3.D NEMA 1, UL 1558": "comply",
            "2.3.E lineup length <= 240 in": "deviate",
            "2.3.F ANSI 61 finish": "comply",
            "2.4.A drawout electrically operated UL 1066": "comply",
            "2.4.B LSIG trip units": "comply",
            "2.4.C ERMS per NEC 240.87": "comply",
            "2.5.A meter accuracy class 0.2": "deviate",
            "2.5.B Modbus TCP and BACnet/IP": "deviate",
            "2.6.A SPD >= 200 kA per phase": "deviate",
            "2.7.A seismic qualification": "missing",
            "3.2.A factory witness testing": "comply",
            "3.3.A manufacturer startup": "missing",
        },
    },
    "bids": {
        "scope": ALPHA_SCOPE,
        "status": {
            "Voltara": {"Freight to site (DDP)": "excluded", "Offloading and rigging at site": "excluded", "Startup and commissioning": "excluded", "Seismic certification": "not_mentioned", "24-month warranty": "qualified"},
            "Northgate": {},
            "Helix": {"Integral surge protective device (SPD)": "excluded", "Arc flash and coordination study": "excluded", "Spare parts": "excluded", "Seismic certification": "excluded", "Owner training": "included", "24-month warranty": "qualified"},
        },
        "arithmetic_errors": {"Helix": {"stated": 991500, "computed": 1004500}},
    },
}

# =============================================================================== PROJECT BETA (held out)

BETA = HERE / "project_beta"

beta_spec = [
    ("h1", "SECTION 23 64 26 - AIR-COOLED CHILLERS"),
    "Project Beta - Hyperscale Campus Building B2, Roof. Chillers CH-1 and CH-2. Issued for Bid.",
    ("h2", "PART 1 - GENERAL"),
    "1.4 WARRANTY. A. Compressor warranty: 5 years parts and labor from startup.",
    ("h2", "PART 2 - PRODUCTS"),
    "2.2 PERFORMANCE. A. Net cooling capacity of each chiller shall be not less than 500 tons at AHRI 550/590 standard rating conditions.",
    "2.2.B Full-load efficiency shall be not more than 1.20 kW/ton.",
    "2.2.C Integrated part-load value (IPLV) shall be not more than 0.80 kW/ton.",
    "2.2.D Refrigerant: global warming potential (GWP) not more than 700.",
    "2.2.E Sound pressure level shall not exceed 78 dBA measured at 30 ft from the unit.",
    "2.2.F Units shall operate at ambient air temperatures up to not less than 125 deg F.",
    "2.3 ELECTRICAL. A. Power supply 460 V, 3-phase, 60 Hz with single-point power connection.",
    "2.3.B Short-circuit current rating of the unit control panel: not less than 65 kA.",
    "2.4 COMPONENTS. A. Compressors: variable-speed oil-free magnetic-bearing centrifugal, or variable-speed screw.",
    "2.4.B Condenser fans: electronically commutated (EC) motors.",
    "2.4.C Condenser coils: factory-applied corrosion-resistant e-coat.",
    "2.4.D Integral air-side free-cooling coils with automatic changeover.",
    "2.4.E Controls: native BACnet/IP interface to the BMS.",
    "2.5 STRUCTURAL. A. Operating weight of each unit shall not exceed 30,000 lb (roof structural limit).",
    ("h2", "PART 3 - EXECUTION"),
    "3.1 TESTING. A. Factory performance test witnessed by the Owner per AHRI 550/590.",
    "END OF SECTION",
]

beta_submittal = [
    ("h1", "PRODUCT SUBMITTAL - AIR-COOLED CHILLERS CH-1/CH-2"),
    "Manufacturer: Frostline Thermal Systems (fictional). Model: FL-AC500M (fictional). Quantity: 2.",
    ("h2", "Performance at AHRI 550/590 conditions"),
    (
        "table",
        [
            ["Item", "Value"],
            ["Net capacity", "1,700 kW"],
            ["Full-load efficiency", "1.18 kW/ton"],
            ["IPLV", "0.78 kW/ton"],
            ["Refrigerant", "R-1234ze(E), GWP < 1"],
            ["Sound pressure", "80 dBA at 10 m"],
            ["Maximum ambient", "52 °C"],
        ],
        [2.2 * inch, 4.4 * inch],
    ),
    ("h2", "Electrical"),
    "460 V / 3 ph / 60 Hz, single-point power connection with non-fused disconnect. Panel SCCR: 35 kA.",
    ("h2", "Construction"),
    "Compressors: two oil-free magnetic-bearing centrifugal compressors with integral variable-speed drives.",
    "Condenser fans: EC fan motors with variable speed control.",
    "Coils: standard aluminum microchannel condenser coils. Corrosion-resistant coating available as an option (not included).",
    "Free cooling: integral free-cooling coil section with automatic changeover valve.",
    "Controls: Frostline FT-Touch controller with BACnet MS/TP. BACnet/IP available via optional communication card.",
    "PAGE",
    ("h2", "Physical"),
    "Operating weight: 13,600 kg per unit. Shipping weight: 12,900 kg.",
    ("h2", "Warranty"),
    "Compressor warranty: 5 years parts only; labor covered for the first year from startup.",
]

BETA_SCOPE = [
    "Two air-cooled chillers per Section 23 64 26",
    "Freight to site",
    "Crane and rigging to roof",
    "Factory startup",
    "Factory performance test",
    "BMS integration",
    "Vibration isolation",
    "5-year compressor warranty",
    "Owner training",
]

beta_bids = {
    "bid_frostline.pdf": bid_doc(
        "PROPOSAL FTS-4410 - AIR-COOLED CHILLERS, PROJECT BETA",
        "Frostline Thermal Systems (fictional)",
        "Two (2) FL-AC500M air-cooled chillers per Section 23 64 26.",
        [
            ("Two FL-AC500M chillers", 1240000),
            ("Freight to jobsite", 18000),
            ("Factory startup", 14000),
            ("Factory performance test, witnessed", 9000),
            ("Spring vibration isolators", 6500),
            ("Owner training", 3000),
        ],
        1290500,
        ["Compressor warranty 5 years parts only."],
        ["Crane and rigging excluded.", "BMS integration by controls contractor."],
        ["Valid 30 days."],
        "28 weeks from release.",
    ),
    "bid_coolstream.pdf": bid_doc(
        "QUOTE CS-2210 - PROJECT BETA CHILLERS",
        "CoolStream HVAC Equipment (fictional)",
        "Two air-cooled chillers, variable-speed screw, per Section 23 64 26.",
        [
            ("Two VS-screw air-cooled chillers, 510 tons each", 1185000),
            ("Freight", 21000),
            ("Crane and rigging to roof", 26000),
            ("Startup", 12000),
            ("BMS integration, BACnet/IP", 15000),
            ("Extended 5-year compressor warranty, parts and labor", 22000),
            ("Training", 4000),
        ],
        1285000,
        [],
        ["Factory performance test not included.", "Vibration isolation by others."],
        ["Valid 60 days."],
        "36 weeks from release.",
    ),
}

beta_truth = {
    "compliance": {
        "spec": "spec_23_64_26_chillers.pdf",
        "submittal": "submittal_frostline_chillers.pdf",
        "labels": {
            "1.4.A compressor warranty 5y parts+labor": "deviate",
            "2.2.A capacity >= 500 tons": "deviate",
            "2.2.B full-load <= 1.20 kW/ton": "comply",
            "2.2.C IPLV <= 0.80": "comply",
            "2.2.D GWP <= 700": "comply",
            "2.2.E sound <= 78 dBA @30ft": "deviate",
            "2.2.F ambient >= 125F": "comply",
            "2.3.A 460/3/60 single point": "comply",
            "2.3.B SCCR >= 65 kA": "deviate",
            "2.4.A mag-bearing or VS screw": "comply",
            "2.4.B EC fans": "comply",
            "2.4.C e-coat coils": "deviate",
            "2.4.D free cooling": "comply",
            "2.4.E BACnet/IP native": "deviate",
            "2.5.A weight <= 30000 lb": "comply",
            "3.1.A witnessed factory performance test": "missing",
        },
    },
    "bids": {
        "scope": BETA_SCOPE,
        "status": {
            "Frostline": {"Crane and rigging to roof": "excluded", "BMS integration": "excluded", "5-year compressor warranty": "qualified"},
            "CoolStream": {"Factory performance test": "excluded", "Vibration isolation": "excluded"},
        },
        "arithmetic_errors": {"Frostline": {"stated": 1290500, "computed": 1290500}, "CoolStream": {"stated": 1285000, "computed": 1285000}},
    },
}
# fix: no arithmetic errors in Beta -> remove entries (kept explicit for readability above)
beta_truth["bids"]["arithmetic_errors"] = {}

# =============================================================================== schedules / POs

ALPHA_SCHEDULE = [
    # id, name, duration_days, predecessors, requires_po
    ("A100", "Notice to proceed", 0, "", ""),
    ("A110", "Electrical room ER-1 and roof structure ready", 210, "A100", ""),
    ("A120", "Set LV switchgear SWG-1", 10, "A110", "PO-1001"),
    ("A130", "Pull and terminate feeders", 25, "A120", ""),
    ("A140", "Set pad-mounted transformers", 7, "A110", "PO-1002"),
    ("A150", "Set standby generators", 14, "A110", "PO-1003"),
    ("A160", "Utility energization", 10, "A130;A140", ""),
    ("A170", "Set UPS modules", 10, "A110", "PO-1004"),
    ("A180", "Set chillers on roof", 12, "A110", "PO-1005"),
    ("A190", "Mechanical piping tie-in", 30, "A180", ""),
    ("A200", "Level 3 commissioning", 25, "A160;A150;A170;A190", ""),
    ("A210", "Integrated systems test (Level 5)", 15, "A200", ""),
    ("A220", "Substantial completion", 0, "A210", ""),
]

ALPHA_POS = [
    # po, item, vendor, order_date, quoted_lead_weeks, shipment_mode, status
    ("PO-1001", "480V switchgear lineup SWG-1, 4000 A", "Voltara Power Systems (fictional)", "2026-12-15", 34, "Ocean", "Submittal under review"),
    ("PO-1002", "2500 kVA pad-mounted transformers (2)", "Indus Transformers (fictional)", "2026-11-20", 50, "Truck", "In fabrication"),
    ("PO-1003", "3000 kW diesel standby generator sets (2)", "Konark Power Gen (fictional)", "2026-10-05", 56, "Ocean", "In fabrication"),
    ("PO-1004", "1.2 MW modular UPS systems (4)", "Arcline Critical Power (fictional)", "2027-01-05", 26, "Air", "Shop drawings approved"),
    ("PO-1005", "500-ton air-cooled chillers (2)", "Frostline Thermal Systems (fictional)", "2027-01-10", 28, "Ocean", "Submittal returned - revise and resubmit"),
]


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    pdf(ALPHA / "spec_26_23_00_lv_switchgear.pdf", alpha_spec)
    pdf(ALPHA / "submittal_voltara_swg1.pdf", alpha_submittal)
    for name, blocks in alpha_bids.items():
        pdf(ALPHA / name, blocks)
    write_csv(ALPHA / "schedule.csv", ["activity_id", "name", "duration_days", "predecessors", "requires_po"], ALPHA_SCHEDULE)
    pos = []
    for po, item, vendor, od, lw, mode, status in ALPHA_POS:
        promised = (date.fromisoformat(od) + timedelta(weeks=lw)).isoformat()
        pos.append((po, item, vendor, od, lw, promised, mode, status))
    write_csv(
        ALPHA / "purchase_orders.csv",
        ["po_number", "item", "vendor", "order_date", "quoted_lead_weeks", "promised_date", "shipment_mode", "status"],
        pos,
    )
    (ALPHA / "project.json").write_text(json.dumps({"name": "Project Alpha - Data Center DC-1", "start_date": "2026-12-01", "target_completion": "2028-01-31"}, indent=1))
    (ALPHA / "ground_truth.json").write_text(json.dumps(alpha_truth, indent=1))
    (ALPHA / "scope_checklist.json").write_text(json.dumps(ALPHA_SCOPE, indent=1))

    pdf(BETA / "spec_23_64_26_chillers.pdf", beta_spec)
    pdf(BETA / "submittal_frostline_chillers.pdf", beta_submittal)
    for name, blocks in beta_bids.items():
        pdf(BETA / name, blocks)
    (BETA / "ground_truth.json").write_text(json.dumps(beta_truth, indent=1))
    (BETA / "scope_checklist.json").write_text(json.dumps(BETA_SCOPE, indent=1))
    print("samples written to", HERE)


if __name__ == "__main__":
    main()
