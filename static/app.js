"use strict";

const $ = id => document.getElementById(id);
const overviewLabels = {theme:"核心主题", audience:"目标用户", pain:"用户痛点", benefit:"产品核心利益", genre:"文案类型", structure:"整体结构", emotion:"情绪曲线", persuasion:"说服逻辑", conversion:"转化策略"};
const sentenceLabels = {meaning:"中文释义", role:"文案组件", function:"表达功能", purpose:"营销目的", mechanism:"说服机制", emotion:"情绪作用", transition:"上下文衔接", syntax:"英文句式结构", chunks:"核心语块", reuse:"复用价值", tags:"分类标签"};
const states = {review:"待审核", writing:"写入中", failed:"待重试", done:"已完成"};
const choices = {pending:"待审核", approved:"通过", rejected:"驳回"};
const tabs = {overview:"整篇分析", sentences:"逐句拆解", assets:"英文表达资产", logic:"说服逻辑", manifest:"写入清单"};
const levels = {L1:"Phrase Chunks", L2:"Sentence Patterns", L3:"Expression Frameworks"};
const demo = "Still digging through your bag for your keys? I used to do that every morning. Now I clip them right here. One click, and I'm out the door. Try it on your next commute.";
let config = {}, jobs = [], job = null, tab = "overview", dirty = false, busy = false, polling, noticeTimer;
const mock = value => String(value).toLowerCase() === "mock";
const modeLabel = value => mock(value) ? "Mock 模拟" : value || "未知";

function element(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}
const div = (cls, ...children) => element("div", {className:cls}, ...children);
const button = (text, fn, cls = "secondary") => element("button", {type:"button", textContent:text, className:cls, onclick:fn});
const h = (tag, text) => element(tag, {textContent:text});
function message(text, error = false) {
  clearTimeout(noticeTimer);
  const notice = $("notice");
  notice.textContent = text;
  notice.className = error ? "error" : "";
  notice.hidden = false;
  noticeTimer = setTimeout(() => notice.hidden = true, error ? 12000 : 4300);
}
async function api(path, method = "GET", data) {
  const options = {method};
  if (data !== undefined) {
    options.headers = {"Content-Type":"application/json"};
    options.body = JSON.stringify(data);
  }
  const res = await fetch("/api/" + path, options);
  let result;
  try { result = await res.json(); } catch { throw new Error("服务器返回了无法读取的响应（HTTP " + res.status + "）"); }
  if (!res.ok) {
    const detail = result.detail || result.error || result.message || ("HTTP " + res.status);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return result;
}
function locked(action) {
  return async () => {
    if (busy) return;
    busy = true;
    document.querySelector(".workspace").inert = true;
    try { await action(); } catch (err) { message(err.message || String(err), true); }
    finally { document.querySelector(".workspace").inert = false; busy = false; }
  };
}
function screen(name) {
  clearTimeout(polling);
  for (const id of ["compose","history","review"]) $(id).hidden = name !== id;
  $("new-nav").classList.toggle("active", name !== "history");
  $("history-nav").classList.toggle("active", name === "history");
  $("breadcrumb").textContent = {compose:"文案工作台",history:"分析历史",review:"分析与审核"}[name];
  window.scrollTo(0,0);
}
function leaveEdits() {
  return !dirty || window.confirm("此报告有尚未保存的修改。离开并放弃这些修改？");
}
async function refreshHistory() {
  jobs = await api("jobs");
  $("history-count").textContent = String(jobs.length);
}
function header(title, description, accessory) {
  return div("heading", div("", h("h1",title), h("p",description)), accessory);
}
function historyPage() {
  const panel = div("panel");
  if (!jobs.length) panel.append(div("empty","还没有分析记录。提交第一段英文口播后，可在这里继续审核。"));
  for (const row of jobs) {
    const open = button(row.title || row.id, locked(async () => showJob(await api("jobs/" + encodeURIComponent(row.id)))), "history-title");
    panel.append(div("list-row",div("",open,h("small",row.id)),element("span",{className:"tag",textContent:states[row.state] || row.state})));
  }
  $("history").replaceChildren(header("分析历史","打开已保存的报告，继续审核或查看写入记录。"),panel);
}
$("new-nav").onclick = () => {
  if (busy || !leaveEdits()) return;
  dirty = false; job = null; screen("compose");
};
$("history-nav").onclick = locked(async () => {
  if (!leaveEdits()) return;
  await refreshHistory(); dirty = false; job = null; screen("history"); historyPage();
});
const form = $("compose-form");
function countText() {
  const text = $("script-text").value;
  $("counter").textContent = (text.trim() ? text.trim().split(/\s+/).length : 0) + " 词 · " + [...text].length + " 字符";
}
$("script-text").oninput = countText;
$("sample").onclick = () => {
  if (form.text.value.trim() && !window.confirm("用示例文案和产品信息替换当前输入？")) return;
  Object.assign(form.text,{value:demo}); form.product.value = "Key Clip"; form.category.value = "通勤配件";
  form.benefits.value = "将钥匙扣在包上，出门时方便取用。"; form.video.value = ""; countText();
};
form.onsubmit = event => {
  event.preventDefault();
  if (!form.text.value.trim()) { message("请先输入英文口播原文。",true); return; }
  locked(async () => {
    $("analyze").textContent = "正在分析…";
    try {
      const result = await api("jobs","POST",Object.fromEntries(new FormData(form)));
      showJob(result); await refreshHistory();
    } finally { $("analyze").textContent = "✦ 开始分析"; }
  })();
};
function showJob(result, active = "overview") {
  job = result; dirty = false; tab = active; screen("review"); renderReport();
  if (job.state === "writing") {
    const id = job.id;
    polling = setTimeout(async () => {
      try { const fresh = await api("jobs/" + encodeURIComponent(id)); if (job?.id === id) showJob(fresh,tab); }
      catch (err) { message(err.message,true); }
    }, 2200);
  }
}
const editable = () => job?.state === "review";
function markDirty() {
  if (dirty) return;
  dirty = true;
  if ($("save-review")) $("save-review").disabled = false;
  if ($("save-status")) $("save-status").textContent = "有未保存的修改";
  if ($("confirm-write")) $("confirm-write").disabled = true;
}
function select(options, value, change, label) {
  const node = element("select",{disabled:!editable()});
  node.setAttribute("aria-label",label);
  for (const [key,text] of Object.entries(options)) node.append(element("option",{value:key,textContent:text}));
  node.value = value; node.onchange = () => {change(node.value); markDirty();};
  return node;
}
function field(obj,key,label,options) {
  const value = obj[key] ?? "";
  const isList = Array.isArray(value);
  let control;
  if (options) control = select(options,value,v => {obj[key] = v;},label);
  else {
    control = element("textarea",{value:isList ? value.join("\n") : value, rows:2,disabled:!editable()});
    control.oninput = () => {
      obj[key] = isList ? control.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean) : control.value;
      markDirty();
    };
  }
  return element("label",{className:"field"},label + (isList ? "（每行一项）" : ""),control);
}
function original(text) {return element("blockquote",{className:"original",lang:"en",textContent:text});}
function sourcePanel() {
  const input = job.input;
  const metadata = [["产品",input.product],["类目",input.category],["卖点",input.benefits],["视频",input.video]]
    .filter(([,v]) => v).map(([k,v]) => div("data-row",h("strong",k),v));
  return element("details",{className:"origin-meta"},h("summary","查看原始文案与产品信息"),original(input.text),...metadata);
}
const decisionCount = status => job.decisions.filter(item => item === status).length;
function bulk(status) {
  job.decisions.fill(status); markDirty(); renderReport();
}
function renderSentences() {
  const section = div("");
  if (editable()) section.append(div("actions",button("全部通过",() => bulk("approved")),button("全部驳回",() => bulk("rejected")),button("全部重置为待审",() => bulk("pending"))));
  job.report.sentences.forEach((s,i) => {
    const decision = select(choices,job.decisions[i],v => {job.decisions[i] = v;}, "第 " + (i+1) + " 句审核决定");
    decision.className = "review-select";
    const fields = Object.entries(sentenceLabels).map(([k,label]) => field(s,k,label,k === "role" ? {Hook:"Hook",Body:"Body",CTA:"CTA"} : null));
    section.append(div("panel",div("panel-head",h("h2","第 " + (i+1) + " 句"),decision),original(s.original),div("fields",fields)));
  });
  return section;
}
function renderAssets() {
  const section = div("");
  for (const [index,a] of job.report.assets.entries()) {
    const scope = {"通用":"跨品类通用","产品专属":"产品专属"};
    section.append(div("panel",div("panel-head",h("h2",a.level + " · " + levels[a.level]),h("small","资产 " + (index+1))),
      div("original","来源语句 · " + a.sources.join("、")),
      div("fields",field(a,"template","英文模板 / 语块"),field(a,"scope","复用范围",scope),
        field(a,"scene","适用场景"),field(a,"limits","使用限制"),field(a,"tags","分类标签"))));
  }
  if (!job.report.assets.length) section.append(div("panel empty","这段文案没有可提取的表达资产。"));
  return section;
}
function manifest() {
  const target = mock(job.storage) ? "本地模拟库" : "飞书多维表格";
  const section = div("panel",div("panel-head",h("h2","最终写入清单"),h("small",target)));
  if (dirty) {
    section.append(h("p","请先保存修改，系统将根据最新审核结果重新生成清单。")); return section;
  }
  const plan = job.plan || [];
  section.append(h("p","已通过 " + decisionCount("approved") + " 句 · 已驳回 " + decisionCount("rejected") + " 句 · 待审核 " + decisionCount("pending") + " 句"));
  for (const item of plan) {
    const receipt = job.receipts?.find(row => row.table === item.table && row.key === item.key);
    section.append(div("list-row",div("",h("strong",item.title || item.key),h("small",item.table + " · " + item.key)),
      element("span",{className:"tag",textContent:receipt ? receipt.record_id : "待处理"})));
  }
  if (!plan.length) section.append(div("empty","当前没有待写入记录。"));
  if (job.state === "review" || job.state === "failed") {
    const confirm = button(job.state === "failed" ? "重试已确认的写入" : mock(job.storage) ? "确认并模拟写入" : "确认并写入飞书",locked(async () => {
      if (!window.confirm("确认将清单中的 " + plan.length + " 项提交到" + target + "？已确认的审核版本将锁定。")) return;
      confirm.textContent = "正在处理…";
      try {
        const result = await api("jobs/" + encodeURIComponent(job.id) + "/confirm","POST",{revision:job.revision,confirmed:true});
        showJob(result,"manifest"); await refreshHistory();
      } finally {if (confirm.isConnected) renderReport();}
    }),"primary");
    confirm.id = "confirm-write";
    confirm.disabled = !plan.length || job.decisions.includes("pending") || !decisionCount("approved");
    if (confirm.disabled) section.append(h("p","请在「逐句拆解」中完成每个组件的审核，并至少通过一个组件。"));
    section.append(div("actions",confirm));
  }
  return section;
}
function logPanel() {
  const section = element("details",{className:"panel"},h("summary","分析、审核与写入日志"));
  for (const l of job.logs || []) section.append(div("data-row",h("strong",l.event),String(l.time || "") + " " + (typeof l.detail === "object" ? JSON.stringify(l.detail) : l.detail || "")));
  return section;
}
function renderReport() {
  const nav = div("tabs");
  for (const [key,title] of Object.entries(tabs)) {
    const btn = button(title,() => {tab = key; renderReport();}, "tab" + (tab === key ? " selected" : ""));
    btn.setAttribute("aria-pressed",String(tab === key)); nav.append(btn);
  }
  const builders = {
    overview:() => div("panel",div("fields",Object.entries(overviewLabels).map(([k,label]) => field(job.report.overview,k,label)))),
    sentences:renderSentences, assets:renderAssets,
    logic:() => div("",job.report.sentences.map((s,i) => div("panel",h("h2","第 " + (i+1) + " 句"),original(s.original),div("fields",field(s,"logic","在全文中的作用与推进关系"),field(s,"stages","说服环节"))))),
    manifest
  };
  const info = "分析引擎 " + modeLabel(job.analysis) + " · 写入目标 " + (mock(job.storage) ? "本地模拟库" : "飞书多维表格");
  const content = [header("分析与审核",info,element("span",{className:"tag",textContent:states[job.state] || job.state})),sourcePanel(),nav];
  if (job.error) content.push(div("danger",String(job.error)));
  content.push(builders[tab]());
  if (tab === "manifest") content.push(logPanel());
  if (editable()) {
    const save = button("保存审核结果",locked(async () => {
      const result = await api("jobs/" + encodeURIComponent(job.id),"PUT",{revision:job.revision,report:job.report,decisions:job.decisions});
      showJob(result,"manifest"); message("审核结果已保存，请核对写入清单。");
    }),"primary");
    save.id = "save-review"; save.disabled = !dirty;
    content.push(div("save-bar",element("p",{id:"save-status",textContent:dirty ? "有未保存的修改" : "当前审核版本已保存"}),div("actions",save)));
  }
  $("review").replaceChildren(...content);
}
window.addEventListener("beforeunload", e => {if (dirty) {e.preventDefault();e.returnValue = ""; }});
(async () => {
  try {
    config = await api("config");
    $("analysis-mode").textContent = modeLabel(config.analysis);
    $("storage-mode").textContent = modeLabel(config.storage);
    $("mobile-mode").textContent = mock(config.storage) ? "本地模拟写入" : "飞书写入";
    await refreshHistory();
  } catch (err) {message(err.message,true);}
})();

