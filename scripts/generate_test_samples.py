"""Generate high-quality test PDF documents for Passport, Emirates ID, and Driving License."""
import pymupdf as fitz
import os

os.makedirs("test_docs", exist_ok=True)

# 1. Emirates ID sample
doc_eid = fitz.open()
page = doc_eid.new_page(width=600, height=380)
page.draw_rect(fitz.Rect(10, 10, 590, 370), color=(0.1, 0.4, 0.7), fill=(0.95, 0.97, 1.0), width=2)
page.insert_text(fitz.Point(30, 45), "UNITED ARAB EMIRATES", fontsize=18, fontname="helv", color=(0.1, 0.2, 0.5))
page.insert_text(fitz.Point(30, 70), "FEDERAL AUTHORITY FOR IDENTITY, CITIZENSHIP, CUSTOMS & PORT SECURITY", fontsize=9, fontname="helv")
page.insert_text(fitz.Point(30, 95), "RESIDENT IDENTITY CARD / بطاقة هوية", fontsize=14, fontname="helv", color=(0.7, 0.1, 0.1))

page.insert_text(fitz.Point(30, 140), "ID Number / رقم الهوية:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(180, 140), "784-1994-3849102-7", fontsize=13, fontname="helv", color=(0, 0, 0))

page.insert_text(fitz.Point(30, 175), "Name:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(180, 175), "MOHAMMED SALEM AL NUAIMI", fontsize=13, fontname="helv")

page.insert_text(fitz.Point(30, 210), "Nationality / الجنسية:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(180, 210), "United Arab Emirates / الإمارات", fontsize=12, fontname="helv")

page.insert_text(fitz.Point(30, 245), "Date of Birth / تاريخ الميلاد:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(210, 245), "14/05/1994", fontsize=12, fontname="helv")

page.insert_text(fitz.Point(30, 280), "Gender / الجنس:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(180, 280), "M", fontsize=12, fontname="helv")

page.insert_text(fitz.Point(30, 315), "Expiry Date / تاريخ الانتهاء:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(210, 315), "13/05/2029", fontsize=12, fontname="helv", color=(0.6, 0, 0))

page.insert_text(fitz.Point(30, 350), "Card Number:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(180, 350), "10984729104", fontsize=10, fontname="helv")

doc_eid.save("test_docs/sample_emirates_id.pdf")
doc_eid.close()

# 2. Passport sample
doc_pass = fitz.open()
page = doc_pass.new_page(width=580, height=400)
page.draw_rect(fitz.Rect(10, 10, 570, 390), color=(0.2, 0.2, 0.2), fill=(0.98, 0.98, 0.96), width=2)
page.insert_text(fitz.Point(40, 50), "PASSPORT / PASSEPORT", fontsize=16, fontname="helv", color=(0.1, 0.1, 0.4))
page.insert_text(fitz.Point(40, 75), "UNITED ARAB EMIRATES / EMIRATS ARABES UNIS", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(40, 120), "Type / Code / Passport No.:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(220, 120), "P / ARE / N98765432", fontsize=13, fontname="helv", color=(0.8, 0.1, 0.1))

page.insert_text(fitz.Point(40, 155), "Surname / Nom:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(220, 155), "AL NUAIMI", fontsize=13, fontname="helv")

page.insert_text(fitz.Point(40, 190), "Given Names / Prénoms:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(220, 190), "MOHAMMED SALEM", fontsize=13, fontname="helv")

page.insert_text(fitz.Point(40, 225), "Nationality / Nationalité:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(220, 225), "EMIRATI / ARE", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(40, 260), "Date of Birth / Date de naissance:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(250, 260), "14/05/1994", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(40, 290), "Sex / Sexe:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(220, 290), "M", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(40, 320), "Date of Expiry / Date d'expiration:", fontsize=10, fontname="helv")
page.insert_text(fitz.Point(250, 320), "20/08/2032", fontsize=11, fontname="helv")

# MRZ Lines at bottom
page.insert_text(fitz.Point(30, 360), "P<AREAL<NUAIMI<<MOHAMMED<SALEM<<<<<<<<<<<<<<<<<<", fontsize=10, fontname="courier")
page.insert_text(fitz.Point(30, 375), "N987654321ARE9405148M3208204<<<<<<<<<<<<<<<02", fontsize=10, fontname="courier")

doc_pass.save("test_docs/sample_passport.pdf")
doc_pass.close()

# 3. Driving License sample
doc_dl = fitz.open()
page = doc_dl.new_page(width=580, height=360)
page.draw_rect(fitz.Rect(10, 10, 570, 350), color=(0.1, 0.5, 0.2), fill=(0.96, 0.99, 0.96), width=2)
page.insert_text(fitz.Point(30, 45), "UNITED ARAB EMIRATES - DUBAI RTA", fontsize=15, fontname="helv", color=(0.1, 0.4, 0.2))
page.insert_text(fitz.Point(30, 70), "DRIVING LICENCE / رخصة قيادة", fontsize=13, fontname="helv", color=(0, 0, 0))

page.insert_text(fitz.Point(30, 115), "Licence No / رقم الرخصة:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(220, 115), "5154695", fontsize=13, fontname="helv", color=(0.7, 0.1, 0.1))

page.insert_text(fitz.Point(30, 150), "Name / الاسم:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(220, 150), "MOHAMMED SALEM AL NUAIMI", fontsize=12, fontname="helv")

page.insert_text(fitz.Point(30, 185), "Nationality / الجنسية:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(220, 185), "United Arab Emirates", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(30, 220), "Date of Birth / تاريخ الميلاد:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(230, 220), "14/05/1994", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(30, 255), "Licensing Authority / سلطة الترخيص:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(260, 255), "EDC20007 / Dubai RTA", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(30, 290), "Traffic Code No / الرمز المروري:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(240, 290), "17165557", fontsize=11, fontname="helv")

page.insert_text(fitz.Point(30, 325), "Expiry Date / تاريخ الانتهاء:", fontsize=11, fontname="helv")
page.insert_text(fitz.Point(230, 325), "09/11/2030", fontsize=11, fontname="helv")

doc_dl.save("test_docs/sample_driving_license.pdf")
doc_dl.close()

print("✅ Generated 3 test document PDFs in test_docs/")
