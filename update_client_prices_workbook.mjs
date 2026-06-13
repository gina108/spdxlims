import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/SPDXLIMS/client_prices.xlsx";
const outputPath = "C:/SPDXLIMS/client_prices.updated.xlsx";

const file = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(file);

const rulesSheet = workbook.worksheets.getOrAdd("Instrument Rules");
const rulesRange = rulesSheet.getUsedRange();
if (rulesRange) {
  rulesRange.clear({ applyTo: "all" });
}

const ruleRows = [
  ["test_code", "test_name", "specimen_type", "instrument_category", "allowed_profiles", "matching_notes"],
  ["EGO-ASP", "Aspecto de la orina", "urine", "manual_or_visual", "", "Manual/visual result; do not auto-import from strip reader by default."],
  ["EGO-COL", "Color de la orina", "urine", "manual_or_visual", "", "Manual/visual result; do not auto-import from strip reader by default."],
  ["EGO-BIL", "Bilirrubina en orina", "urine", "urinalysis_strip", "urinalysis-com6", "Matches strip-reader bilirubin result."],
  ["EGO-CET", "Cetonas en orina", "urine", "urinalysis_strip", "urinalysis-com6", "Matches strip-reader ketone result."],
  ["EGO-DEN", "Densidad urinaria", "urine", "urinalysis_strip", "urinalysis-com6", "Matches strip-reader SG / specific gravity result."],
  ["EGO-EST", "Esterasa leucocitaria", "urine", "urinalysis_strip", "urinalysis-com6", "Matches strip-reader LEU result."],
  ["EGO-ERI", "Eritrocitos en sedimento", "urine", "urinalysis_strip", "urinalysis-com6", "Review mapping if instrument BLO should feed this code directly."],
  ["EGO-GLU", "Glucosa en orina", "urine", "urinalysis_strip", "urinalysis-com6", "Add this code to the catalog/importer if urine glucose is auto-posted."],
  ["EGO-NIT", "Nitritos en orina", "urine", "urinalysis_strip", "urinalysis-com6", "Add this code to the catalog/importer if nitrite is auto-posted."],
  ["EGO-PH", "pH urinario", "urine", "urinalysis_strip", "urinalysis-com6", "Add this code to the catalog/importer if pH is auto-posted."],
  ["EGO-PRO", "Proteinas en orina", "urine", "urinalysis_strip", "urinalysis-com6", "Add this code to the catalog/importer if protein is auto-posted."],
  ["EGO-URO", "Urobilinogeno en orina", "urine", "urinalysis_strip", "urinalysis-com6", "Add this code to the catalog/importer if urobilinogen is auto-posted."],
];

rulesSheet.getRange(`A1:F${ruleRows.length}`).values = ruleRows;
rulesSheet.getRange("A1:F1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
};
rulesSheet.freezePanes.freezeRows(1);
rulesSheet.getRange("A:F").format.autofitColumns();

const instructionsSheet = workbook.worksheets.getItem("Instructions");
instructionsSheet.getRange("A7:B8").values = [
  ["Instrument matching / Coincidencia de equipos", "Use the Instrument Rules sheet to tag which tests can be auto-imported from each analyzer profile. Keep pricing columns unchanged. / Use la hoja Instrument Rules para indicar que analitos pueden importarse automaticamente desde cada perfil de analizador. Mantenga sin cambios las columnas de precios."],
  ["Why this sheet exists / Por que existe esta hoja", "The same clinical code can appear on different machines, so analyzer eligibility must be tracked separately from test_code. / El mismo codigo clinico puede aparecer en diferentes equipos, por lo que la elegibilidad del analizador debe registrarse por separado del test_code."],
];
instructionsSheet.getRange("A7:B8").format.wrapText = true;
instructionsSheet.getRange("A1:B8").format.autofitRows();
instructionsSheet.getRange("A:B").format.autofitColumns();

await fs.mkdir("C:/SPDXLIMS", { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const verify = await workbook.inspect({
  kind: "table",
  sheetId: "Instrument Rules",
  range: `A1:F${ruleRows.length}`,
  include: "values",
  tableMaxRows: 20,
  tableMaxCols: 6,
  maxChars: 5000,
});

process.stdout.write(verify.ndjson);
