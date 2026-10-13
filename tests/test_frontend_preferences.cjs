const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/preferences.js'),'utf8');
const context={};vm.createContext(context);vm.runInContext(source,context);
const t=context.EvoJevPreferences.t;
const cases=[
  ['Results','总览'],['Evolution','演进'],['Cases','案例'],['Method','方法'],
  ['Benchmark','基准'],['Correct','正确'],['Incorrect','错误'],
  ['754 / 754 cases','754 / 754 个案例'],['60 RULES','60 条规则'],
  ['48 rule admission steps','48 次规则准入'],
  ['454 correct / 754 diagnosed','454 题正确 / 754 题已诊断'],
  ['H49 used for this diagnosis','本次诊断使用 H49'],
  ['H49 → H50 · 1 new rules','H49 → H50 · 1 条新规则'],
  ['Stream 206 · Harness 49','序列 206 · Harness 49'],
  ['Recorded output · 10000 characters · excerpt','已记录输出 · 10000 字符 · 摘录'],
  ['Recorded PUCT · 96 simulations · 3-call horizon','已记录 PUCT · 96 次模拟 · 3 次调用视野'],
  ['First answer saved before feedback · 0 new inference calls during export','反馈之前保存首答 · 导出期间 0 次新推理调用'],
  ['Move Executable Harness','移动 可执行 Harness'],
  ['Post-case update','题后更新'],['Next Harness version: 50','下一个 Harness 版本：50']
];
for(const [english,chinese] of cases){assert.equal(t(english,'zh'),chinese);assert.equal(t(english,'en'),english);}
assert.equal(t('  Correct\n','zh'),'  正确\n');
for(const raw of ['case_0143','app/shippingservice','code_busy_loop','60.21%','Service Performance Degradation.','{"fault_object":"app/shippingservice"}'])assert.equal(t(raw,'zh'),raw);
assert.match(source,/collect\(observer\.takeRecords\(\)\);observer\.disconnect\(\)/);
assert.match(source,/evojev-theme/);assert.match(source,/evojev-language/);
console.log('Preferences: translation, technical-data preservation and pending-mutation checks passed.');
