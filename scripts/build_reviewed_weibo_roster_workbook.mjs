import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const require = createRequire('C:/Users/86183/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {Workbook, SpreadsheetFile, FileBlob} = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const directory = path.resolve('data/weibo/2026-05-26_2026-10-20/参赛名单');
const data = JSON.parse(await fs.readFile(path.join(directory, '参赛人名名单.json'), 'utf8'));
const workbook = Workbook.create();
const sheet = workbook.worksheets.add('参赛人名总表');
sheet.showGridLines = false;
const headers = Object.keys(data.people[0]);
const first = 7, last = first + data.people.length - 1;
const rows = data.people.map(person => headers.map(header => {
  if (['首次排班日期','最近排班日期'].includes(header)) return new Date(`${person[header]}T00:00:00Z`);
  return person[header];
}));
sheet.getRange(`A2:L${last}`).format.font = {name:'Arial', size:11, color:'#243447'};
sheet.getRange('A2').values = [['京城大师赛 S22 至今参赛人名名单']];
sheet.getRange('A2').format.font = {name:'Arial', size:16, bold:true};
sheet.getRange('A2:L2').format.rowHeight = 30;
sheet.getRange('A3:H3').values = [['去重人数', null, 'S22人数', null, 'S23人数', null, '两季都参加', null]];
sheet.getRange('B3').formulas = [[`=COUNTA(B${first}:B${last})`]];
sheet.getRange('D3').formulas = [[`=COUNTIFS(D${first}:D${last},">0")`]];
sheet.getRange('F3').formulas = [[`=COUNTIFS(E${first}:E${last},">0")`]];
sheet.getRange('H3').formulas = [[`=COUNTIFS(D${first}:D${last},">0",E${first}:E${last},">0")`]];
sheet.getRange('A3:H3').format.rowHeight = 26;
sheet.getRange('A4').values = [[`资料采集至 ${data.summary.as_of}，本批排班赛日至 ${data.summary.last_schedule_date}。排班日数按日期去重。`]];
sheet.getRange('A4').format.font = {name:'Arial', size:10, color:'#526477'};
sheet.getRange('A4:L4').format.rowHeight = 23;
sheet.getRangeByIndexes(5, 0, 1, headers.length).values = [headers];
sheet.getRangeByIndexes(6, 0, rows.length, headers.length).values = rows;
const table = sheet.tables.add(`A6:L${last}`, true, 'ReviewedRoster');
table.showFilterButton = true;
sheet.getRange(`A6:L${last}`).format.rowHeight = 24;
sheet.getRange(`A6:L${last}`).format.verticalAlignment = 'center';
sheet.getRange(`A6:L${last}`).format.horizontalAlignment = 'left';
sheet.getRange('A6:L6').format = {fill:'#284B63', font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},
  horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:34};
for (const [col,width] of Object.entries({A:8,B:18,C:15,D:16,E:16,F:17,G:16,H:16,I:21,J:15,K:28,L:38})) {
  sheet.getRange(`${col}2:${col}${last}`).format.columnWidth = width;
}
sheet.getRange(`G${first}:H${last}`).setNumberFormat('yyyy-mm-dd');
for(const col of ['A','D','E','F','J']) {
  sheet.getRange(`${col}${first}:${col}${last}`).setNumberFormat('0');
  sheet.getRange(`${col}${first}:${col}${last}`).format.horizontalAlignment = 'right';
}
sheet.freezePanes.freezeRows(6);
workbook.recalculate();
const metrics = ['B3','D3','F3','H3'].map(address => sheet.getRange(address).values[0][0]);
const expected = [data.summary.unique_people,data.summary.season_people.S22,data.summary.season_people.S23,data.summary.both_seasons];
if (metrics.some((v,i)=>v!==expected[i])) throw Error(`Summary formulas mismatch: ${JSON.stringify(metrics)}`);
console.log((await workbook.inspect({kind:'table',range:'参赛人名总表!A3:H10',tableMaxRows:8,tableMaxCols:8,maxChars:1500})).ndjson);
const preview = await workbook.render({sheetName:sheet.name,range:'A2:H16',scale:1.25,format:'png'});
await fs.writeFile(path.join(directory,'参赛人名总表_预览.png'),new Uint8Array(await preview.arrayBuffer()));
const output = path.join(directory,'京城大师赛_S22至今_参赛人名总表.xlsx');
await (await SpreadsheetFile.exportXlsx(workbook)).save(output);
const saved = await SpreadsheetFile.importXlsx(await FileBlob.load(output));
const exported = saved.worksheets.getItem(sheet.name).getRange(`B${first}:B${last}`).values.flat();
if(exported.length!==data.people.length || exported.some((name,i)=>name!==data.people[i]['姓名'])) throw Error('Exported names mismatch');
const report = {status:'passed',people:exported.length,unique_names:new Set(exported).size,metrics,all_exported_names_match_source:true};
await fs.writeFile(path.join(directory,'人名总表_Excel验收.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
