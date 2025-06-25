import csv
from pypdf import PdfReader, PdfWriter

def extract_pages(input_pdf, page_range, output_pdf):
    reader = PdfReader(input_pdf)
    writer = PdfWriter()

    # Seitenbereich splitten
    start, end = map(int, page_range.split('-'))
    for page_num in range(start - 1, end):
        writer.add_page(reader.pages[page_num])

    with open(output_pdf, 'wb') as f_out:
        writer.write(f_out)

def main():
    with open('extract_list.csv', 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            page_range = row['page_range'].strip()
            input_pdf = row['input_pdf'].strip()
            output_pdf = row['output_pdf'].strip()

            if not output_pdf.lower().endswith('.pdf'):
                output_pdf += '.pdf'

            extract_pages(input_pdf, page_range, output_pdf)
            print(f"Erstellt: {output_pdf}")

if __name__ == "__main__":
    main()
