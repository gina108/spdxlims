import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/SPDXLIMS/client_prices.xlsx";
const file = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(file);
const summary = await workbook.inspect({
  kind: "sheet,table",
  include: "id,name",
  maxChars: 6000,
  tableMaxRows: 20,
  tableMaxCols: 20,
});

process.stdout.write(summary.ndjson);
