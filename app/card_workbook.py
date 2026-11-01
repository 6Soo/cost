"""Read issuer XLSX exports without changing any source cells or formats."""
import io
import zipfile
from xml.etree import ElementTree as ET


def load_card_workbook(content, *, data_only, reader=None):
    if reader is None:
        from openpyxl import load_workbook
        reader = load_workbook

    # Some issuer generators add styleId and lowercase xfid to xf records.
    # They are presentation metadata, not cell identities or number formats.
    with zipfile.ZipFile(io.BytesIO(content)) as source:
        if sum(info.file_size for info in source.infolist()) > 64 * 1024 * 1024:
            raise ValueError('expanded workbook too large')
        if 'xl/styles.xml' in source.namelist():
            root = ET.fromstring(source.read('xl/styles.xml'))
            changed = False
            for xf in root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}xf'):
                if 'styleId' in xf.attrib:
                    del xf.attrib['styleId']
                    changed = True
                if 'xfid' in xf.attrib:
                    value = xf.attrib.pop('xfid')
                    if 'xfId' in xf.attrib and xf.attrib['xfId'] != value:
                        raise ValueError('conflicting style parent')
                    xf.attrib['xfId'] = value
                    changed = True
            if changed:
                result = io.BytesIO()
                with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as target:
                    for info in source.infolist():
                        target.writestr(info, ET.tostring(root) if info.filename == 'xl/styles.xml'
                                        else source.read(info.filename))
                content = result.getvalue()
    workbook = reader(io.BytesIO(content), data_only=data_only, read_only=True)
    # Issuer print exports incorrectly declare A1:A1 despite having data below.
    # Scan actual cells for both parsing and the independent formula check.
    for sheet in workbook.worksheets:
        sheet.reset_dimensions()
    return workbook
