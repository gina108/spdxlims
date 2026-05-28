from __future__ import annotations

REGIMEN_FISCAL_OPTIONS: tuple[tuple[str, str], ...] = (
    ('601', '601 - General de Ley Personas Morales'),
    ('603', '603 - Personas Morales con Fines no Lucrativos'),
    ('605', '605 - Sueldos y Salarios e Ingresos Asimilados a Salarios'),
    ('621', '621 - Incorporacion Fiscal'),
    ('625', '625 - Actividades Empresariales con ingresos a traves de plataformas tecnologicas'),
)

USO_CFDI_OPTIONS: tuple[tuple[str, str], ...] = (
    ('G01', 'G01 - Adquisicion de mercancias'),
    ('G03', 'G03 - Gastos en general'),
    ('D01', 'D01 - Honorarios medicos, dentales y gastos hospitalarios'),
    ('P01', 'P01 - Por definir'),
    ('S01', 'S01 - Sin efectos fiscales'),
)

FORMA_PAGO_OPTIONS: tuple[tuple[str, str], ...] = (
    ('01', '01 - Efectivo'),
    ('02', '02 - Cheque nominativo'),
    ('03', '03 - Transferencia electronica de fondos'),
    ('99', '99 - Por definir'),
)

METODO_PAGO_OPTIONS: tuple[tuple[str, str], ...] = (
    ('PUE', 'PUE - Pago en una sola exhibicion'),
    ('PPD', 'PPD - Pago en parcialidades o diferido'),
)
