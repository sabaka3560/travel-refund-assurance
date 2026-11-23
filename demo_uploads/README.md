# Demo uploads

Specimen e-tickets and realistic flight ticket images for testing the extraction step of the console.

Drag any file (PDF or PNG/JPG image) onto the upload zone on the Demo tab. Gemini reads it against a strict schema, fills the form, and you check the fields before computing.

Every file is marked **SPECIMEN — DEMONSTRATION DOCUMENT — NOT A GENUINE TICKET** or represents a simulated passenger receipt. Fare and tax structures are realistic for Indian domestic travel (K3 = GST at 5% of base fare for economy; UDF and PSF vary by airport).

Regenerate PDFs and companion PNGs with `python _generate.py`.

---

## 1. High-Resolution E-Ticket Documents (PDF & PNG)

Each document is available in both `.pdf` format and crisp `.png` image format (rendered at 300 DPI, 1786×2526 px):

| PDF File | PNG Image File | Carrier | Tests |
|---|---|---|---|
| `01_spicejet_DEL-BOM.pdf` | `01_spicejet_DEL-BOM.png` | SpiceJet | **The clean case.** Every tax itemised, fare family printed, YR surcharge and convenience fee. Booked 20 Nov 2025 (*before* the 12-Dec-2025 rule change). |
| `02_indigo_DEL-BLR.pdf` | `02_indigo_DEL-BLR.png` | IndiGo | **No fare family printed** — realistic for IndiGo, and harmless because its table has no fare-family dimension. |
| `03_airindia_DEL-BOM_flex.pdf` | `03_airindia_DEL-BOM_flex.png` | Air India | **Full refund.** Economy Flex cancelled >72h out carries no cancellation fee. |
| `04_akasa_BLR-BOM_flexi.pdf` | `04_akasa_BLR-BOM_flexi.png` | Akasa | **An evidence gap made visible.** Booked after Akasa's stated 12-May-2026 date, but the preserved capture predates it, so the rule is capped at LOW. |
| `05_airindia_express_BLR-COK.pdf` | `05_airindia_express_BLR-COK.png` | AI Express | **Different rule shape** — a 3-day band from the mandatory-disclosure PDF. |
| `06_makemytrip_invoice_LUMPED_TAX.pdf` | `06_makemytrip_invoice_LUMPED_TAX.png` | OTA invoice | **The realistic failure.** A single combined "Taxes & fees" line instead of itemised codes — the extractor flags it, because the statutory line cannot be computed from a lump sum. |
| `07_spicejet_CORPORATE.pdf` | `07_spicejet_CORPORATE.png` | SpiceJet | **Partial answer.** Corporate account code means the retail table does not govern; fare line abstains while statutory taxes compute as a labelled PARTIAL total. |
| — | `08_indigo_BLR-HYD_photo.png` | IndiGo | **Image path** — mobile phone style specimen image testing image-based OCR directly. |

---

## 2. Realistic Generated Airline Flight Ticket Images

Photorealistic generated airline flight ticket and passenger receipt images featuring authentic airline branding, barcodes, QR codes, and realistic paper textures:

| Image File | Carrier | Details & Route |
|---|---|---|
| `real_spicejet_flight_ticket.jpg` | SpiceJet | SG 8194, Delhi (DEL) to Mumbai (BOM), PNR QK7T2M, Ramesh Iyer, ₹8,420 total. |
| `real_indigo_flight_ticket.jpg` | IndiGo | 6E 2043, Delhi (DEL) to Bengaluru (BLR), PNR P4RJ9K, Ananya Desai, ₹6,378 total. |
| `real_airindia_flight_ticket.jpg` | Air India | AI 866, Delhi (DEL) to Mumbai (BOM), PNR 7HQ2ZB, Vikram Menon, Economy Flex, ₹10,213 total. |
| `real_akasa_flight_ticket.jpg` | Akasa Air | QP 1408, Bengaluru (BLR) to Mumbai (BOM), PNR AK5W8N, Priya Nair, Flexi, ₹5,600 total. |
| `real_aiexpress_flight_ticket.jpg` | Air India Express | IX 1132, Bengaluru (BLR) to Kochi (COK), PNR IX3M6D, Sunil Raghavan, Classic, ₹4,130 total. |

---

## 3. Recommended Demos

- **`06_makemytrip_invoice_LUMPED_TAX.png`:** Demonstrates that the extractor flags lumped taxes rather than guessing a statutory tax breakdown, prompting the user before computing.
- **`07_spicejet_CORPORATE.png`:** Demonstrates corporate negotiated fare handling where the fare line abstains while statutory taxes compute as a labelled `PARTIAL` refund.
- **`01_spicejet_DEL-BOM.png` vs Booking Date Shift:** Demonstrates how changing only the booking date across 12-Dec-2025 changes the refund from **₹4,720.00** to **₹4,021.00**.
