from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from spdxlims.database import ClientRecord, InvoiceRecord, LabSettingsRecord


def write_cfdi_preview_xml(path: str | Path, *, settings: LabSettingsRecord, client: ClientRecord, invoice: InvoiceRecord) -> Path:
    root = Element('cfdi:Comprobante', {
        'Version': '4.0',
        'Serie': 'A',
        'Folio': invoice.invoice_number,
        'Fecha': f'{invoice.invoice_date}T12:00:00',
        'Moneda': invoice.currency or 'MXN',
        'SubTotal': f'{invoice.total_amount:.2f}',
        'Total': f'{invoice.total_amount:.2f}',
        'TipoDeComprobante': 'I',
        'Exportacion': '01',
        'LugarExpedicion': settings.sat_postal_code or '',
        'xmlns:cfdi': 'http://www.sat.gob.mx/cfd/4',
    })
    SubElement(root, 'cfdi:Emisor', {
        'Rfc': settings.sat_rfc or '',
        'Nombre': settings.lab_name or '',
        'RegimenFiscal': settings.sat_fiscal_regime or '',
    })
    SubElement(root, 'cfdi:Receptor', {
        'Rfc': client.tax_id or '',
        'Nombre': client.name or '',
        'DomicilioFiscalReceptor': client.postal_code or '',
        'RegimenFiscalReceptor': client.fiscal_regime or '',
        'UsoCFDI': invoice.cfdi_use or client.cfdi_use or '',
    })
    conceptos = SubElement(root, 'cfdi:Conceptos')
    SubElement(conceptos, 'cfdi:Concepto', {
        'ClaveProdServ': '85121800',
        'Cantidad': '1',
        'ClaveUnidad': 'ACT',
        'Descripcion': invoice.notes or f'Servicios de laboratorio {invoice.order_number or invoice.invoice_number}',
        'ValorUnitario': f'{invoice.total_amount:.2f}',
        'Importe': f'{invoice.total_amount:.2f}',
        'ObjetoImp': '01',
    })
    target = Path(path)
    target.write_text('<?xml version=\"1.0\" encoding=\"utf-8\"?>\n' + tostring(root, encoding='unicode'), encoding='utf-8')
    return target
