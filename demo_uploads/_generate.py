"""Generate demo e-ticket PDFs (and one PNG) for testing the extraction pipeline.

These are SPECIMEN documents with fictional passengers, built to exercise the
extractor against realistic Indian-domestic ticket layouts. Each is marked as a
specimen so it can never be mistaken for a genuine travel document.

    python _generate.py
"""
from __future__ import annotations

import os
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = A4

GREY = HexColor("#5A6572")
DARK = HexColor("#16202B")
LINE = HexColor("#D3DAE2")
SOFT = HexColor("#F2F5F8")


def rupee(n):
    return "INR {:,.2f}".format(n)


def draw(c, spec):
    brand = HexColor(spec["brand"])
    y = H - 22 * mm

    # ---- header band
    c.setFillColor(brand)
    c.rect(0, H - 30 * mm, W, 30 * mm, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(18 * mm, H - 17 * mm, spec["airline"])
    c.setFont("Helvetica", 8.5)
    c.drawString(18 * mm, H - 23 * mm, spec["doc_title"])
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(W - 18 * mm, H - 15 * mm, "BOOKING REF / PNR")
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(W - 18 * mm, H - 22 * mm, spec["pnr"])

    y = H - 40 * mm

    # ---- specimen marker
    c.setFillColor(HexColor("#B03A24"))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(18 * mm, y, "SPECIMEN — DEMONSTRATION DOCUMENT — NOT A GENUINE TICKET")
    y -= 8 * mm

    # ---- passenger / ticket block
    def kv(x, label, value, bold=False, size=9.5):
        c.setFillColor(GREY)
        c.setFont("Helvetica", 7)
        c.drawString(x, y, label.upper())
        c.setFillColor(DARK)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y - 5.2 * mm, value)

    kv(18 * mm, "Passenger", spec["pax"], bold=True)
    kv(88 * mm, "Ticket number", spec["tkt"])
    kv(140 * mm, "Date of issue", spec["issue"])
    y -= 14 * mm

    kv(18 * mm, "Booking date", spec["booking"])
    kv(88 * mm, "Fare type", spec.get("fare_family") or "—", bold=bool(spec.get("fare_family")))
    kv(140 * mm, "Status", "CONFIRMED")
    y -= 16 * mm

    if spec.get("corporate"):
        c.setFillColor(HexColor("#7A4E00"))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(18 * mm, y, "CORPORATE NEGOTIATED FARE   ·   Account code: " + spec["corporate"])
        y -= 9 * mm

    # ---- flight table
    c.setFillColor(SOFT)
    c.rect(18 * mm, y - 22 * mm, W - 36 * mm, 28 * mm, stroke=0, fill=1)
    c.setStrokeColor(LINE)
    c.rect(18 * mm, y - 22 * mm, W - 36 * mm, 28 * mm, stroke=1, fill=0)

    c.setFillColor(GREY)
    c.setFont("Helvetica-Bold", 7)
    for x, t in [(23, "FLIGHT"), (48, "FROM"), (88, "TO"), (128, "DEPARTS"), (166, "ARRIVES")]:
        c.drawString(x * mm, y + 1 * mm, t)

    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(23 * mm, y - 7 * mm, spec["flight"])
    c.drawString(48 * mm, y - 7 * mm, spec["from_code"])
    c.drawString(88 * mm, y - 7 * mm, spec["to_code"])
    c.setFont("Helvetica", 8)
    c.drawString(48 * mm, y - 12 * mm, spec["from_city"])
    c.drawString(88 * mm, y - 12 * mm, spec["to_city"])
    c.setFont("Helvetica-Bold", 10)
    c.drawString(128 * mm, y - 7 * mm, spec["dep_time"])
    c.drawString(166 * mm, y - 7 * mm, spec["arr_time"])
    c.setFont("Helvetica", 8)
    c.drawString(128 * mm, y - 12 * mm, spec["dep_date"])
    c.drawString(166 * mm, y - 12 * mm, spec["dep_date"])
    c.setFont("Helvetica", 7.5)
    c.setFillColor(GREY)
    c.drawString(23 * mm, y - 18 * mm, "Cabin: " + spec.get("cabin", "Economy") +
                 ("   ·   Class: " + spec["rbd"] if spec.get("rbd") else ""))

    y -= 34 * mm

    # ---- fare breakdown
    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(18 * mm, y, "Fare breakdown")
    y -= 3 * mm
    c.setStrokeColor(LINE)
    c.line(18 * mm, y, W - 18 * mm, y)
    y -= 7 * mm

    for label, amount in spec["lines"]:
        c.setFillColor(DARK)
        c.setFont("Helvetica", 9.5)
        c.drawString(20 * mm, y, label)
        c.drawRightString(W - 20 * mm, y, rupee(amount))
        y -= 6.5 * mm

    y -= 1 * mm
    c.setStrokeColor(HexColor("#9AA6B4"))
    c.setLineWidth(1.1)
    c.line(18 * mm, y, W - 18 * mm, y)
    c.setLineWidth(1)
    y -= 7 * mm
    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 11.5)
    c.drawString(20 * mm, y, "Total amount paid")
    c.drawRightString(W - 20 * mm, y, rupee(spec["total"]))
    y -= 14 * mm

    # ---- fare conditions
    c.setFillColor(GREY)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(18 * mm, y, "FARE CONDITIONS")
    y -= 5 * mm
    c.setFont("Helvetica", 7.8)
    for ln in spec["conditions"]:
        c.drawString(18 * mm, y, ln)
        y -= 4.4 * mm

    # ---- footer
    c.setFillColor(HexColor("#8A96A3"))
    c.setFont("Helvetica", 7)
    c.drawString(18 * mm, 14 * mm, spec["footer"])
    c.drawRightString(W - 18 * mm, 14 * mm, "Specimen document generated for software testing")


TICKETS = [
    dict(
        file="01_spicejet_DEL-BOM.pdf", airline="SpiceJet", brand="#B4131C",
        doc_title="E-TICKET ITINERARY / RECEIPT", pnr="QK7T2M",
        pax="RAMESH IYER (MR)", tkt="775-2416890341", issue="20 Nov 2025", booking="20 Nov 2025",
        fare_family="SpiceSaver", flight="SG 8194", rbd="L",
        from_code="DEL", from_city="Delhi T1", to_code="BOM", to_city="Mumbai T2",
        dep_time="18:00", arr_time="20:10", dep_date="15 Jan 2026",
        lines=[("Base fare", 6700.00), ("K3 — Goods & Services Tax", 352.00),
               ("UDF — User Development Fee", 708.00), ("PSF — Passenger Service Fee", 160.00),
               ("YR — Carrier imposed surcharge", 250.00), ("Convenience fee", 250.00)],
        total=8420.00,
        conditions=["Cancellation permitted up to 4 hours before scheduled departure.",
                    "Cancellation charges apply as per the fare rules in force at the time of booking.",
                    "Statutory taxes including UDF, ADF and PSF are refundable on cancellation.",
                    "Convenience fee is non-refundable."],
        footer="SpiceJet Limited · specimen"),

    dict(
        file="02_indigo_DEL-BLR.pdf", airline="IndiGo", brand="#12206A",
        doc_title="E-TICKET / ITINERARY RECEIPT", pnr="P4RJ9K",
        pax="ANANYA DESAI (MS)", tkt="312-7745120983", issue="15 Oct 2025", booking="15 Oct 2025",
        fare_family=None, flight="6E 2043", rbd="R",
        from_code="DEL", from_city="Delhi T3", to_code="BLR", to_city="Bengaluru T1",
        dep_time="06:20", arr_time="09:15", dep_date="20 Jan 2026",
        lines=[("Base fare", 5400.00), ("K3 — GST", 270.00),
               ("UDF — User Development Fee", 708.00)],
        total=6378.00,
        conditions=["Cancellation fee depends on the time of cancellation.",
                    "Cancellation permitted up to 3 hours prior to departure on domestic flights.",
                    "Applicable statutory taxes will be refunded."],
        footer="InterGlobe Aviation Limited · specimen"),

    dict(
        file="03_airindia_DEL-BOM_flex.pdf", airline="Air India", brand="#B01E2E",
        doc_title="ELECTRONIC TICKET ITINERARY / RECEIPT", pnr="7HQ2ZB",
        pax="VIKRAM MENON (MR)", tkt="098-3391750264", issue="01 Jun 2026", booking="01 Jun 2026",
        fare_family="Economy Flex", flight="AI 866", rbd="Y",
        from_code="DEL", from_city="Delhi T3", to_code="BOM", to_city="Mumbai T2",
        dep_time="08:15", arr_time="10:25", dep_date="20 Sep 2026",
        lines=[("Base fare", 8900.00), ("K3 — GST", 445.00),
               ("UDF — User Development Fee", 708.00), ("PSF — Passenger Service Fee", 160.00)],
        total=10213.00,
        conditions=["Economy Flex: no cancellation charge when cancelled more than 72 hours before departure.",
                    "Within 72 hours of departure a cancellation charge of INR 2,500 applies.",
                    "Fare rules applicable at the time of booking take precedence."],
        footer="Air India Limited · specimen"),

    dict(
        file="04_akasa_BLR-BOM_flexi.pdf", airline="Akasa Air", brand="#E05A1E",
        doc_title="E-TICKET ITINERARY RECEIPT", pnr="AK5W8N",
        pax="PRIYA NAIR (MS)", tkt="141-8823097451", issue="10 Jun 2026", booking="10 Jun 2026",
        fare_family="Flexi", flight="QP 1408", rbd="T",
        from_code="BLR", from_city="Bengaluru T2", to_code="BOM", to_city="Mumbai T1",
        dep_time="14:40", arr_time="16:25", dep_date="25 Sep 2026",
        lines=[("Base fare", 4800.00), ("K3 — GST", 240.00),
               ("UDF — User Development Fee", 560.00)],
        total=5600.00,
        conditions=["Cancellation charges effective for bookings made from 12 May 2026 onwards.",
                    "100% of airfare is forfeited for cancellations made within 4 hours of departure.",
                    "Statutory taxes remain refundable."],
        footer="Akasa Air (SNV Aviation) · specimen"),

    dict(
        file="05_airindia_express_BLR-COK.pdf", airline="Air India Express", brand="#E2601A",
        doc_title="E-TICKET ITINERARY / RECEIPT", pnr="IX3M6D",
        pax="SUNIL RAGHAVAN (MR)", tkt="098-6612480375", issue="01 Jul 2026", booking="01 Jul 2026",
        fare_family="Classic", flight="IX 1132", rbd="S",
        from_code="BLR", from_city="Bengaluru T1", to_code="COK", to_city="Kochi",
        dep_time="11:05", arr_time="12:20", dep_date="15 Oct 2026",
        lines=[("Base fare", 3400.00), ("K3 — GST", 170.00),
               ("UDF — User Development Fee", 560.00)],
        total=4130.00,
        conditions=["Classic fare: cancellation charge INR 2,000 up to 3 days before departure.",
                    "Within 3 days to 2 hours of departure the cancellation charge is INR 3,000.",
                    "Cancellation not permitted within 2 hours of scheduled departure."],
        footer="Air India Express Limited · specimen"),

    dict(
        file="06_makemytrip_invoice_LUMPED_TAX.pdf", airline="MakeMyTrip", brand="#E03A3E",
        doc_title="TAX INVOICE — AIR TICKET (booked on Air India)", pnr="MMT94QZ1",
        pax="KAVITA SHARMA (MS)", tkt="098-4417260938", issue="01 May 2026", booking="01 May 2026",
        fare_family=None, flight="AI 619", rbd="U",
        from_code="DEL", from_city="Delhi T3", to_code="BLR", to_city="Bengaluru T1",
        dep_time="18:00", arr_time="20:55", dep_date="18 Aug 2026",
        lines=[("Base fare", 6700.00), ("Taxes & fees", 1220.00)],
        total=7920.00,
        conditions=["Airline cancellation charges apply as per the fare rules of the operating carrier.",
                    "MakeMyTrip convenience fee is non-refundable.",
                    "Refunds are processed after receipt from the airline."],
        footer="MakeMyTrip India Pvt Ltd · specimen"),

    dict(
        file="07_spicejet_CORPORATE.pdf", airline="SpiceJet", brand="#B4131C",
        doc_title="E-TICKET ITINERARY / RECEIPT — CORPORATE BOOKING", pnr="CQ2L8V",
        pax="ARJUN BHATIA (MR)", tkt="775-9930418266", issue="10 Jan 2026", booking="10 Jan 2026",
        fare_family="SpiceSaver Corporate", flight="SG 8194", rbd="L",
        corporate="ACME-IN-4471",
        from_code="DEL", from_city="Delhi T1", to_code="BOM", to_city="Mumbai T2",
        dep_time="18:00", arr_time="20:10", dep_date="01 Apr 2026",
        lines=[("Base fare", 6700.00), ("K3 — GST", 352.00),
               ("UDF — User Development Fee", 708.00), ("PSF — Passenger Service Fee", 160.00)],
        total=7920.00,
        conditions=["Corporate negotiated fare. Cancellation terms as per the corporate agreement.",
                    "Refer to your corporate travel desk for applicable cancellation charges."],
        footer="SpiceJet Limited · corporate programme · specimen"),
]


def main():
    for spec in TICKETS:
        path = os.path.join(OUT, spec["file"])
        c = canvas.Canvas(path, pagesize=A4)
        c.setTitle(spec["airline"] + " specimen e-ticket")
        draw(c, spec)
        c.showPage()
        c.save()
        print("wrote", spec["file"])

        # Render companion PNG image
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(path)
            img = pdf[0].render(scale=3.0).to_pil()
            png_path = os.path.splitext(path)[0] + ".png"
            img.save(png_path)
            print("wrote", os.path.basename(png_path))
        except Exception as e:
            print(f"could not render PNG for {spec['file']}: {e}")

    # Generate specimen photo PNG
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (1240, 1754), "white")
        d = ImageDraw.Draw(img)
        try:
            fb = ImageFont.truetype("arialbd.ttf", 44)
            fh = ImageFont.truetype("arialbd.ttf", 26)
            fr = ImageFont.truetype("arial.ttf", 24)
            fs = ImageFont.truetype("arial.ttf", 19)
        except OSError:
            fb = fh = fr = fs = ImageFont.load_default()
        d.rectangle([0, 0, 1240, 150], fill="#12206A")
        d.text((60, 42), "IndiGo", font=fb, fill="white")
        d.text((60, 100), "E-TICKET / ITINERARY RECEIPT", font=fs, fill="#D5DBEF")
        d.text((900, 50), "PNR  W8T4RQ", font=fh, fill="white")
        d.text((60, 190), "SPECIMEN — DEMONSTRATION DOCUMENT — NOT A GENUINE TICKET",
               font=fs, fill="#B03A24")
        rows = [
            ("Passenger", "MEERA KRISHNAN (MS)"), ("Ticket number", "312-5580219476"),
            ("Booking date", "02 Oct 2025"), ("Date of issue", "02 Oct 2025"),
            ("Flight", "6E 6172"), ("Route", "BLR Bengaluru  to  HYD Hyderabad"),
            ("Departs", "07:30   on   10 Jan 2026"), ("Fare type", "not shown"),
        ]
        y = 260
        for k, v in rows:
            d.text((60, y), k.upper(), font=fs, fill="#5A6572")
            d.text((360, y - 4), v, font=fr, fill="#16202B")
            y += 52
        y += 26
        d.text((60, y), "FARE BREAKDOWN", font=fh, fill="#16202B"); y += 52
        for k, v in [("Base fare", "INR 4,500.00"), ("K3 - GST", "INR 236.00"),
                     ("UDF - User Development Fee", "INR 708.00"),
                     ("PSF - Passenger Service Fee", "INR 160.00")]:
            d.text((80, y), k, font=fr, fill="#16202B")
            d.text((900, y), v, font=fr, fill="#16202B"); y += 46
        d.line([60, y + 10, 1180, y + 10], fill="#9AA6B4", width=3); y += 40
        d.text((80, y), "Total amount paid", font=fh, fill="#16202B")
        d.text((900, y), "INR 5,604.00", font=fh, fill="#16202B")
        y += 90
        d.text((60, y), "Cancellation fee depends on the time of cancellation.", font=fs, fill="#5A6572")
        d.text((60, y + 32), "Applicable statutory taxes will be refunded.", font=fs, fill="#5A6572")
        p = os.path.join(OUT, "08_indigo_BLR-HYD_photo.png")
        img.save(p)
        print("wrote 08_indigo_BLR-HYD_photo.png")


if __name__ == "__main__":
    main()
