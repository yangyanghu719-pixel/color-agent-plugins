EXPERIMENT_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>色彩构成实验台</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Microsoft YaHei", Arial, sans-serif; color: #1f2933; background: #f3f6f8; }
    header { padding: 22px 28px 12px; background: #fff; border-bottom: 1px solid #d7dee7; }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
    main { display: grid; grid-template-columns: minmax(300px, 1.2fr) minmax(300px, .9fr); gap: 16px; padding: 18px 28px 28px; }
    .toolbar, .panel, .analysis { background: #fff; border: 1px solid #d7dee7; border-radius: 8px; padding: 14px; }
    .toolbar { grid-column: 1 / -1; display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: center; }
    input[type="url"], input[type="file"] { width: 100%; min-height: 40px; border: 1px solid #c8d2dc; border-radius: 6px; padding: 8px 10px; background: #fff; }
    button { min-height: 40px; border: 0; border-radius: 6px; padding: 0 14px; color: #fff; background: #0f766e; font-weight: 700; cursor: pointer; white-space: nowrap; }
    button.secondary { background: #475569; }
    button.warning { background: #f59e0b; color: #1f2933; }
    button:disabled { opacity: .45; cursor: not-allowed; }
    h2 { margin: 0 0 12px; font-size: 17px; }
    .stage { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .image-box { min-height: 270px; border: 1px dashed #b7c3cf; border-radius: 8px; background: #eef3f6; display: flex; align-items: center; justify-content: center; overflow: hidden; color: #607080; text-align: center; padding: 10px; }
    .image-box img { max-width: 100%; max-height: 420px; object-fit: contain; display: block; }
    .right-col { display: grid; gap: 16px; align-content: start; }
    .swatches { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .swatch { border: 2px solid transparent; border-radius: 8px; padding: 8px; background: #f8fafc; color: #1f2933; text-align: left; min-width: 0; }
    .swatch.active { border-color: #115e59; }
    .chip { height: 52px; border-radius: 6px; border: 1px solid rgba(0,0,0,.12); margin-bottom: 8px; }
    .swatch strong, .swatch span { display: block; overflow-wrap: anywhere; font-size: 12px; line-height: 1.35; }
    .controls { display: grid; gap: 12px; }
    .slider-row { display: grid; grid-template-columns: 28px 1fr 46px; align-items: center; gap: 10px; font-weight: 700; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; }
    .status, .analysis { grid-column: 1 / -1; }
    .status { min-height: 22px; color: #607080; }
    #analysisResult { white-space: pre-wrap; }
    @media (max-width: 900px) { main, .toolbar, .stage { grid-template-columns: 1fr; } .swatches { grid-template-columns: repeat(2, 1fr); } }
  </style>
</head>
<body>
  <header><h1>色彩构成实验台</h1></header>
  <main>
    <section class="toolbar">
      <input id="imageUrl" type="url" placeholder="输入图片 URL">
      <input id="imageFile" type="file" accept="image/png,image/jpeg,image/webp">
      <button id="segmentBtn">识别主色区域</button>
    </section>
    <section class="status" id="status"></section>
    <section class="panel">
      <h2>原图 / 标注图</h2>
      <div class="stage">
        <div class="image-box" id="originalBox">等待图片</div>
        <div class="image-box" id="annotatedBox">等待识别</div>
      </div>
    </section>
    <section class="right-col">
      <section class="panel">
        <h2>调整后预览</h2>
        <div class="image-box" id="previewBox">等待调整</div>
      </section>
      <section class="panel swatches" id="swatches"></section>
      <section class="panel controls">
        <div class="slider-row"><label for="h">H</label><input id="h" type="range" min="0" max="360" value="0"><span id="hValue">0</span></div>
        <div class="slider-row"><label for="s">S</label><input id="s" type="range" min="0" max="100" value="0"><span id="sValue">0</span></div>
        <div class="slider-row"><label for="l">L</label><input id="l" type="range" min="0" max="100" value="0"><span id="lValue">0</span></div>
        <div class="actions">
          <button id="confirmBtn" class="secondary">确认本次调整</button>
          <button id="analyzeBtn" class="warning">确认并分析</button>
        </div>
      </section>
    </section>
    <section class="analysis">
      <h2>分析结果</h2>
      <div id="analysisResult">暂无分析结果</div>
    </section>
  </main>
  <script>
    const state = { imageUrl: "", displayUrl: "", imageId: "", originalRegions: [], adjustedRegions: [], selectedRegion: null, latestPreviewUrl: "" };
    const $ = (id) => document.getElementById(id);
    const localUrl = "https://example.com/local-experiment.png";
    const isHttp = (url) => /^https?:\\/\\//.test(url);
    const setStatus = (text) => { $("status").textContent = text; };
    const showImage = (id, url) => { $(id).innerHTML = url ? `<img src="${url}" alt="">` : "等待图片"; };
    function syncLabels() { ["h", "s", "l"].forEach((k) => $(`${k}Value`).textContent = $(k).value); }
    function setSliders(hsl) { $("h").value = hsl.h; $("s").value = hsl.s; $("l").value = hsl.l; syncLabels(); }
    function newHsl() { return { h: Number($("h").value), s: Number($("s").value), l: Number($("l").value) }; }
    function renderSwatches() {
      const wrap = $("swatches");
      wrap.innerHTML = "";
      const rows = state.adjustedRegions.slice(0, 4);
      while (rows.length < 4) rows.push(null);
      rows.forEach((region) => {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "swatch" + (region && state.selectedRegion?.id === region.id ? " active" : "");
        card.disabled = !region;
        card.innerHTML = region
          ? `<div class="chip" style="background:${region.hex}"></div><strong>${region.role || region.name}</strong><span>${region.hex} · ${region.percentage}%</span>`
          : `<div class="chip"></div><strong>待识别</strong><span>--</span>`;
        card.onclick = () => { if (region) { state.selectedRegion = region; setSliders(region.hsl); renderSwatches(); } };
        wrap.appendChild(card);
      });
    }
    async function uploadIfNeeded() {
      const file = $("imageFile").files[0];
      if (!file) return null;
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch("/upload-image", { method: "POST", body: form });
      if (!resp.ok) throw new Error(await resp.text());
      return resp.json();
    }
    async function segmentImage() {
      setStatus("正在准备图片...");
      const uploaded = await uploadIfNeeded();
      state.imageUrl = uploaded ? uploaded.image_url : $("imageUrl").value.trim();
      state.displayUrl = uploaded ? uploaded.display_url : state.imageUrl;
      if (!state.imageUrl) { setStatus("请输入图片 URL 或上传本地图片"); return; }
      showImage("originalBox", state.displayUrl);
      const resp = await fetch("/segment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image_url: state.imageUrl, color_count: 4 }) });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      state.imageId = data.image_id;
      state.originalRegions = data.color_regions;
      state.adjustedRegions = JSON.parse(JSON.stringify(data.color_regions));
      state.selectedRegion = state.adjustedRegions[0] || null;
      state.latestPreviewUrl = "";
      showImage("annotatedBox", data.annotated_image_url);
      showImage("previewBox", state.displayUrl);
      if (state.selectedRegion) setSliders(state.selectedRegion.hsl);
      renderSwatches();
      setStatus("已识别主色区域，请选择色块并调整 H/S/L");
    }
    async function confirmAdjustment() {
      if (!state.imageId || !state.selectedRegion) { setStatus("请先识别主色区域并选择色块"); return; }
      const original = state.originalRegions.find((r) => r.id === state.selectedRegion.id);
      const resp = await fetch("/recolor", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        image_id: state.imageId,
        original_image_url: isHttp(state.imageUrl) ? state.imageUrl : localUrl,
        target_region_id: state.selectedRegion.id,
        original_hsl: original.hsl,
        new_hsl: newHsl()
      }) });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      state.latestPreviewUrl = data.preview_image_url;
      state.selectedRegion.hsl = newHsl();
      showImage("previewBox", data.preview_image_url);
      renderSwatches();
      setStatus("本次调整已确认");
    }
    async function analyzeAdjustment() {
      if (!state.originalRegions.length) { setStatus("请先完成识别"); return; }
      const resp = await fetch("/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        original_color_regions: state.originalRegions,
        adjusted_color_regions: state.adjustedRegions,
        before_image_url: isHttp(state.imageUrl) ? state.imageUrl : localUrl,
        after_image_url: isHttp(state.latestPreviewUrl) ? state.latestPreviewUrl : "https://example.com/local-preview.png",
        user_goal: "学生在色彩构成实验台中手动调整 H/S/L"
      }) });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      $("analysisResult").textContent = [`标签：${data.tags.join("、")}`, `色彩关系：${data.color_relation}`, `视觉感受：${data.visual_feeling}`, `适用场景：${data.suitable_scenario}`, `总结：${data.summary}`, `风险：${data.risk}`, `下一步：${data.next_step}`].join("\\n");
      setStatus("分析完成");
    }
    ["h", "s", "l"].forEach((key) => $(key).addEventListener("input", syncLabels));
    $("segmentBtn").onclick = () => segmentImage().catch((err) => setStatus(err.message));
    $("confirmBtn").onclick = () => confirmAdjustment().catch((err) => setStatus(err.message));
    $("analyzeBtn").onclick = () => analyzeAdjustment().catch((err) => setStatus(err.message));
    syncLabels(); renderSwatches();
  </script>
</body>
</html>
"""
