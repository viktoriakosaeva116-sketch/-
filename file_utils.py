import aiofiles

async def extract_txt(file_path: str) -> str:
    encodings = ['utf-8', 'cp1251', 'latin1', 'cp866']
    for encoding in encodings:
        try:
            async with aiofiles.open(file_path, 'r', encoding=encoding) as f:
                content = await f.read()
            return content
        except UnicodeDecodeError:
            continue
    raise Exception("Не удалось определить кодировку файла")

async def extract_docx(file_path: str) -> str:
    try:
        import docx2txt
        return docx2txt.process(file_path)
    except ImportError:
        raise Exception("Установи docx2txt для обработки DOCX")

async def extract_pdf(file_path: str) -> str:
    try:
        import PyPDF2
        content = ""
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text()
                if text and text.strip():
                    content += f"--- Страница {page_num + 1} ---\n{text}\n\n"
        return content
    except ImportError:
        raise Exception("Установи PyPDF2 для обработки PDF")
