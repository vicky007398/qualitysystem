(() => {
  const root = document.documentElement;
  const themeMeta = document.querySelector('[data-theme-color]');
  const themeButtons = [...document.querySelectorAll('[data-theme-toggle]')];
  const appearanceColours = {midnight: '#0d1117', daylight: '#f4f6fa', ocean: '#eef8fc', emerald: '#eff9f3', plum: '#f7f2fb', amber: '#fff8ec'};
  function applyGuestAppearance(appearance) {
    root.dataset.appearance = appearance;
    root.dataset.theme = appearance === 'midnight' ? 'dark' : 'light';
    if (themeMeta) themeMeta.content = appearanceColours[appearance] || appearanceColours.midnight;
  }
  if (root.dataset.appearanceOwner) {
    if (themeMeta) themeMeta.content = appearanceColours[root.dataset.appearance] || appearanceColours.midnight;
  } else {
    let saved; try { saved = localStorage.getItem('qms-theme:guest'); } catch (_) {}
    applyGuestAppearance(saved || root.dataset.appearance || 'midnight');
  }
  themeButtons.forEach(button => button.addEventListener('click', event => {
    if (root.dataset.appearanceOwner) {
      event.stopPropagation();
      const menu = document.querySelector('[data-account-menu]');
      if (menu) { menu.hidden = false; document.querySelector('[data-menu-toggle]')?.setAttribute('aria-expanded','true'); }
    } else {
      const appearance = root.dataset.appearance === 'midnight' ? 'daylight' : 'midnight';
      try { localStorage.setItem('qms-theme:guest', appearance); } catch (_) {}
      applyGuestAppearance(appearance);
    }
  }));
  const sidebarToggle = document.querySelector('[data-sidebar-toggle]');
  if (sidebarToggle) {
    const sidebar = document.getElementById('desktop-sidebar');
    function applySidebar(collapsed) {
      document.body.classList.toggle('sidebar-collapsed', collapsed);
      sidebar.inert = collapsed;
      sidebar.setAttribute('aria-hidden', String(collapsed));
      sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
      sidebarToggle.setAttribute('aria-label', collapsed ? 'Show sidebar' : 'Hide sidebar');
      sidebarToggle.title = collapsed ? 'Show sidebar' : 'Hide sidebar';
      sidebarToggle.querySelector('span').textContent = collapsed ? '→' : '←';
    }
    applySidebar(localStorage.getItem('commercial-demo-sidebar-collapsed') === '1');
    sidebarToggle.addEventListener('click', () => {
      const collapsed = !document.body.classList.contains('sidebar-collapsed');
      applySidebar(collapsed);
      localStorage.setItem('commercial-demo-sidebar-collapsed', collapsed ? '1' : '0');
    });
  }
  document.querySelectorAll('[data-delete-draft]').forEach(deleteForm => {
    deleteForm.addEventListener('submit', event => {
      if (!window.confirm('Delete this unsubmitted draft from your records?')) event.preventDefault();
    });
  });
  document.querySelectorAll('[data-delete-user]').forEach(deleteForm => {
    deleteForm.addEventListener('submit', event => {
      if (!window.confirm('Delete this user account? The user will no longer be able to sign in, but historical reports will remain available.')) event.preventDefault();
    });
  });
  const pageScrollButtons = [...document.querySelectorAll('[data-page-scroll]')];
  if (pageScrollButtons.length) {
    let scrollFrame;
    function updatePageScrollButtons() {
      const top = window.scrollY <= 4;
      const bottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4;
      pageScrollButtons.forEach(button => {
        button.disabled = button.dataset.pageScroll === 'up' ? top : bottom;
      });
    }
    pageScrollButtons.forEach(button => button.addEventListener('click', () => {
      const direction = button.dataset.pageScroll === 'up' ? -1 : 1;
      window.scrollBy({top: direction * Math.max(360, window.innerHeight * .72), behavior: 'smooth'});
    }));
    window.addEventListener('scroll', () => {
      cancelAnimationFrame(scrollFrame);
      scrollFrame = requestAnimationFrame(updatePageScrollButtons);
    }, {passive: true});
    window.addEventListener('resize', updatePageScrollButtons);
    updatePageScrollButtons();
  }
  const menuButton = document.querySelector('[data-menu-toggle]');
  const menu = document.querySelector('[data-account-menu]');
  menuButton?.addEventListener('click', () => {
    menu.hidden = !menu.hidden;
    menuButton.setAttribute('aria-expanded', String(!menu.hidden));
  });
  document.addEventListener('click', event => {
    if (menu && !menu.hidden && !menu.contains(event.target) && !menuButton.contains(event.target)) {
      menu.hidden = true; menuButton.setAttribute('aria-expanded', 'false');
    }
  });

  const form = document.querySelector('#report-form');
  const moduleTabs = [...document.querySelectorAll('[data-module-tab]')];
  const modulePanels = [...document.querySelectorAll('[data-module-panel]')];
  if (moduleTabs.length) {
    const selectedModule = document.querySelector('[data-dashboard-module]')?.dataset.dashboardModule || 'ipqc';
    moduleTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.moduleTab === selectedModule));
    modulePanels.forEach(panel => { panel.hidden = panel.dataset.modulePanel !== selectedModule; });
  }
  if (!form) return;

  function syncMaterialChoice(select) {
    if (!select.matches('[data-material-select]')) return;
    const manual = select.closest('[data-material-choice]')?.querySelector('[data-material-other]');
    if (!manual) return;
    const useManual = select.value === '__other__';
    manual.hidden = !useManual;
    manual.required = useManual && select.required;
    if (!useManual) manual.value = '';
  }

  function materialControlValue(control) {
    if (!control.matches('[data-material-select]') || control.value !== '__other__') return control.value.trim();
    return control.closest('[data-material-choice]')?.querySelector('[data-material-other]')?.value.trim() || '';
  }

  form.querySelectorAll('[data-material-select]').forEach(select => {
    syncMaterialChoice(select);
    select.addEventListener('change', () => {
      syncMaterialChoice(select);
      if (select.value === '__other__') {
        select.closest('[data-material-choice]')?.querySelector('[data-material-other]')?.focus();
      }
    });
  });

  function showGridNotice(message, tone = 'success') {
    let notice = document.querySelector('[data-grid-notice]');
    if (!notice) {
      notice = document.createElement('div');
      notice.className = 'grid-notice';
      notice.dataset.gridNotice = '';
      notice.setAttribute('role', 'status');
      document.body.append(notice);
    }
    notice.dataset.tone = tone;
    notice.textContent = message;
    notice.classList.add('visible');
    clearTimeout(notice._hideTimer);
    notice._hideTimer = setTimeout(() => notice.classList.remove('visible'), 3000);
  }

  const ocrScriptUrl = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js';
  let ocrLoader;
  function loadOcrEngine() {
    if (window.Tesseract) return Promise.resolve(window.Tesseract);
    if (ocrLoader) return ocrLoader;
    ocrLoader = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = ocrScriptUrl;
      script.async = true;
      script.crossOrigin = 'anonymous';
      script.onload = () => window.Tesseract ? resolve(window.Tesseract) : reject(new Error('OCR engine did not initialise'));
      script.onerror = () => reject(new Error('OCR engine could not be downloaded'));
      document.head.append(script);
    });
    return ocrLoader;
  }

  async function renderPdfFirstPage(file) {
    const payload = new FormData();
    const token = document.querySelector('input[name="csrf"]')?.value;
    if (!token) throw new Error('Your session has expired. Reload the page');
    payload.append('csrf', token);
    payload.append('pdf', file, file.name);
    const response = await fetch('/api/render-pdf', {
      method:'POST', body:payload, credentials:'same-origin', headers:{Accept:'image/png'}
    });
    if (!response.ok) {
      const message = (await response.text()).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
      throw new Error(message || `QMS could not render the PDF (${response.status})`);
    }
    const rendered = await response.blob();
    if (!rendered.type.startsWith('image/')) throw new Error('QMS returned an invalid PDF preview');
    return rendered;
  }

  async function prepareOcrPhoto(file) {
    if (!window.createImageBitmap) return file;
    let bitmap;
    try { bitmap = await createImageBitmap(file, {imageOrientation:'from-image'}); }
    catch (error) { return file; }
    const scale = Math.min(2, Math.max(1, 2400 / Math.max(bitmap.width, bitmap.height)));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext('2d', {willReadFrequently:true});
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close();
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    for (let index = 0; index < image.data.length; index += 4) {
      const grey = image.data[index] * .299 + image.data[index + 1] * .587 + image.data[index + 2] * .114;
      const enhanced = Math.max(0, Math.min(255, (grey - 128) * 1.32 + 128));
      image.data[index] = enhanced; image.data[index + 1] = enhanced; image.data[index + 2] = enhanced;
    }
    context.putImageData(image, 0, 0);
    return new Promise(resolve => canvas.toBlob(blob => resolve(blob || file), 'image/jpeg', .95));
  }

  function greenActualCellRects(pixels, width, height) {
    const xCounts = new Uint32Array(width);
    const isGreen = index => {
      const red = pixels[index]; const green = pixels[index + 1]; const blue = pixels[index + 2];
      return green >= 65 && green - red >= 18 && green - blue >= 18 && green >= red * 1.18 && green >= blue * 1.15;
    };
    for (let y = 0; y < height; y += 2) for (let x = 0; x < width; x += 1) {
      if (isGreen((y * width + x) * 4)) xCounts[x] += 1;
    }
    const peak = Math.max(...xCounts);
    if (peak < 12) return [];
    const xRuns = []; let start = -1;
    for (let x = 0; x <= width; x += 1) {
      const active = x < width && xCounts[x] >= Math.max(5, peak * .32);
      if (active && start < 0) start = x;
      if (!active && start >= 0) { if (x - start >= 8) xRuns.push([start, x - 1]); start = -1; }
    }
    if (!xRuns.length) return [];
    const [x0, x1] = xRuns.sort((left, right) => (right[1] - right[0]) - (left[1] - left[0]))[0];
    const yCounts = new Uint32Array(height);
    for (let y = 0; y < height; y += 1) for (let x = x0; x <= x1; x += 2) {
      if (isGreen((y * width + x) * 4)) yCounts[y] += 1;
    }
    const required = Math.max(4, (x1 - x0) * .12);
    const bands = []; start = -1;
    for (let y = 0; y <= height; y += 1) {
      const active = y < height && yCounts[y] >= required;
      if (active && start < 0) start = y;
      if (!active && start >= 0) { if (y - start >= 3) bands.push([start, y - 1]); start = -1; }
    }
    if (bands.length < 8 || bands.length > 13) return [];
    const centers = bands.map(band => (band[0] + band[1]) / 2).sort((left, right) => left - right);
    const spacings = centers.slice(1).map((center, index) => center - centers[index]).sort((left, right) => left - right);
    const spacing = spacings[Math.floor(spacings.length / 2)] || Math.max(8, (bands[0][1] - bands[0][0]) * 1.25);
    const heights = bands.map(band => band[1] - band[0] + 1).sort((left, right) => left - right);
    const cellHeight = heights[Math.floor(heights.length / 2)] || spacing * .75;
    while (centers.length < 12 && centers[centers.length - 1] + spacing < height) centers.push(centers[centers.length - 1] + spacing);
    if (centers.length !== 12) return [];
    return centers.map(center => ({
      x:Math.max(0, x0 - 2), y:Math.max(0, Math.round(center - cellHeight * .55)),
      width:Math.min(width - Math.max(0, x0 - 2), x1 - x0 + 5),
      height:Math.min(height - Math.max(0, Math.round(center - cellHeight * .55)), Math.max(5, Math.round(cellHeight * 1.1))),
    }));
  }

  function numericCellImage(source, rectangle) {
    const sample = document.createElement('canvas');
    sample.width = rectangle.width; sample.height = rectangle.height;
    const sampleContext = sample.getContext('2d', {willReadFrequently:true});
    sampleContext.drawImage(source, rectangle.x, rectangle.y, rectangle.width, rectangle.height, 0, 0, rectangle.width, rectangle.height);
    const image = sampleContext.getImageData(0, 0, sample.width, sample.height);
    const luminance = [];
    for (let index = 0; index < image.data.length; index += 4) {
      luminance.push(image.data[index] * .299 + image.data[index + 1] * .587 + image.data[index + 2] * .114);
    }
    const ordered = [...luminance].sort((left, right) => left - right);
    const median = ordered[Math.floor(ordered.length / 2)] || 128;
    const low = ordered[Math.floor(ordered.length * .12)] || 0;
    const high = ordered[Math.floor(ordered.length * .88)] || 255;
    const threshold = (low + high) / 2;
    const scale = 4; const padding = 10;
    const output = document.createElement('canvas');
    output.width = sample.width * scale + padding * 2; output.height = sample.height * scale + padding * 2;
    const outputContext = output.getContext('2d');
    outputContext.fillStyle = '#fff'; outputContext.fillRect(0, 0, output.width, output.height);
    const binary = sampleContext.createImageData(sample.width, sample.height);
    luminance.forEach((value, pixel) => {
      const foreground = median < 180 ? value > threshold : value < threshold;
      const colour = foreground ? 0 : 255; const index = pixel * 4;
      binary.data[index] = colour; binary.data[index + 1] = colour; binary.data[index + 2] = colour; binary.data[index + 3] = 255;
    });
    sampleContext.putImageData(binary, 0, 0);
    outputContext.imageSmoothingEnabled = false;
    outputContext.drawImage(sample, padding, padding, sample.width * scale, sample.height * scale);
    return output;
  }

  const stringerTemperatureLabels = [
    'Drying Base 1', 'Drying Base 2', 'Drying Base 3', 'Drying Base 4', 'Drying Base 5',
    'Auto-Flux', 'Manual-Flux', 'Preheat Base 1', 'Preheat Base 2', 'Solder Base 1',
    'Solder Base 2', 'Cooling Base Temp',
  ];

  async function readStringerActualCells(file, worker) {
    if (!window.createImageBitmap) return new Map();
    let bitmap;
    try { bitmap = await createImageBitmap(file, {imageOrientation:'from-image'}); }
    catch (error) { return new Map(); }
    const scale = Math.min(1, 1800 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d', {willReadFrequently:true});
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close();
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const rectangles = greenActualCellRects(pixels, canvas.width, canvas.height);
    if (rectangles.length !== stringerTemperatureLabels.length) return new Map();
    await worker.setParameters({tessedit_pageseg_mode:'7', tessedit_char_whitelist:'0123456789.,-'});
    const readings = new Map();
    for (let index = 0; index < rectangles.length; index += 1) {
      const result = await worker.recognize(numericCellImage(canvas, rectangles[index]));
      const values = numericValues(result.data?.text || '');
      if (!values.length) continue;
      readings.set(stringerTemperatureLabels[index], {
        value:values[0], confidence:Math.round(Math.min(99, Number(result.data?.confidence || 0))),
      });
    }
    return readings;
  }

  function normaliseOcrText(value) {
    return String(value || '').toLocaleLowerCase().replace(/[°µ]/g, '')
      .replace(/([0-9])([a-z])/g, '$1 $2').replace(/([a-z])([0-9])/g, '$1 $2')
      .replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function labelTokens(value) {
    const ignored = new Set(['the','and','for','with','per','setting','time','temperature','plate','stringer','laminator','track','recipe']);
    return normaliseOcrText(value).split(' ').filter(token => token && (/^\d+$/.test(token) || (token.length > 1 && !ignored.has(token))));
  }

  function labelScore(label, text) {
    const normalLabel = normaliseOcrText(label);
    const normalText = normaliseOcrText(text);
    if (!normalLabel || !normalText) return 0;
    if (normalText.includes(normalLabel)) return 1;
    const tokens = labelTokens(label);
    if (!tokens.length) return 0;
    const textTokens = new Set(normalText.split(' '));
    const totalWeight = tokens.reduce((total, token) => total + (/^\d+$/.test(token) ? 2 : 1), 0);
    const matchedWeight = tokens.reduce((total, token) => total + (textTokens.has(token) ? (/^\d+$/.test(token) ? 2 : 1) : 0), 0);
    return totalWeight ? matchedWeight / totalWeight : 0;
  }

  function numericValues(text) {
    return [...String(text || '').matchAll(/-?\d+(?:[.,]\d+)?/g)].map(match => match[0].replace(',', '.'));
  }

  function positionedOcrLines(ocrData) {
    const lines = [];
    (ocrData?.blocks || []).forEach(block => (block.paragraphs || []).forEach(paragraph =>
      (paragraph.lines || []).forEach(line => {
        const words = (line.words || []).filter(word => word.text?.trim() && word.bbox).map(word => ({
          text: word.text.trim(), confidence: Number(word.confidence || 0),
          x0: Number(word.bbox.x0), y0: Number(word.bbox.y0), x1: Number(word.bbox.x1), y1: Number(word.bbox.y1),
        })).filter(word => [word.x0, word.y0, word.x1, word.y1].every(Number.isFinite));
        if (words.length) lines.push({
          words, text: words.map(word => word.text).join(' '),
          top: Math.min(...words.map(word => word.y0)), bottom: Math.max(...words.map(word => word.y1)),
        });
      })
    ));
    return lines.sort((left, right) => left.top - right.top || left.words[0].x0 - right.words[0].x0);
  }

  function mergeAlignedOcrLines(lines) {
    const rows = [];
    lines.forEach(line => {
      const height = Math.max(1, line.bottom - line.top);
      const center = (line.top + line.bottom) / 2;
      const row = rows.find(candidate => {
        const candidateHeight = Math.max(1, candidate.bottom - candidate.top);
        const overlap = Math.min(line.bottom, candidate.bottom) - Math.max(line.top, candidate.top);
        return overlap / Math.min(height, candidateHeight) >= .45
          || Math.abs(center - (candidate.top + candidate.bottom) / 2) <= Math.min(height, candidateHeight) * .45;
      });
      if (!row) {
        rows.push({words: [...line.words], top: line.top, bottom: line.bottom});
      } else {
        row.words.push(...line.words);
        row.top = Math.min(row.top, line.top); row.bottom = Math.max(row.bottom, line.bottom);
      }
    });
    return rows.map(row => {
      const seen = new Set();
      row.words = row.words.filter(word => {
        const key = `${word.text}|${word.x0}|${word.y0}|${word.x1}|${word.y1}`;
        if (seen.has(key)) return false;
        seen.add(key); return true;
      }).sort((left, right) => left.x0 - right.x0);
      row.text = row.words.map(word => word.text).join(' ');
      return row;
    }).sort((left, right) => left.top - right.top || left.words[0].x0 - right.words[0].x0);
  }

  function editDistance(left, right) {
    const previous = Array.from({length: right.length + 1}, (_, index) => index);
    for (let i = 1; i <= left.length; i += 1) {
      const current = [i];
      for (let j = 1; j <= right.length; j += 1) {
        current[j] = Math.min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1));
      }
      previous.splice(0, previous.length, ...current);
    }
    return previous[right.length];
  }

  function fuzzyPhraseScore(label, text) {
    const direct = labelScore(label, text);
    const wanted = normaliseOcrText(label).replace(/\s+/g, '');
    if (!wanted) return direct;
    const tokens = normaliseOcrText(text).split(' ').filter(Boolean);
    let fuzzy = 0;
    for (let start = 0; start < tokens.length; start += 1) {
      let phrase = '';
      for (let end = start; end < Math.min(tokens.length, start + 4); end += 1) {
        phrase += tokens[end];
        if (phrase.length < wanted.length * .55 || phrase.length > wanted.length * 1.55) continue;
        fuzzy = Math.max(fuzzy, 1 - editDistance(wanted, phrase) / Math.max(wanted.length, phrase.length));
      }
    }
    return Math.max(direct, fuzzy);
  }

  function stringerPowerGrid(lines) {
    const header = lines.map(line => {
      const channels = line.words.map(word => {
        const values = numericValues(word.text);
        const number = values.length === 1 ? Number(values[0]) : NaN;
        return Number.isInteger(number) && number >= 1 && number <= 24
          ? {number, x:(word.x0 + word.x1) / 2} : null;
      }).filter(Boolean);
      return {line, channels, score:new Set(channels.map(channel => channel.number)).size};
    }).sort((left, right) => right.score - left.score)[0];
    const channelMap = new Map((header?.score >= 4 ? header.channels : []).map(channel => [channel.number, channel.x]));
    if (channelMap.size >= 4) {
      const points = [...channelMap.entries()];
      const meanNumber = points.reduce((total, point) => total + point[0], 0) / points.length;
      const meanX = points.reduce((total, point) => total + point[1], 0) / points.length;
      const numerator = points.reduce((total, point) => total + (point[0] - meanNumber) * (point[1] - meanX), 0);
      const denominator = points.reduce((total, point) => total + (point[0] - meanNumber) ** 2, 0);
      const spacing = denominator ? numerator / denominator : 0;
      if (spacing > 8) {
        const origin = meanX - spacing * meanNumber;
        for (let number = 1; number <= 17; number += 1) {
          if (!channelMap.has(number)) channelMap.set(number, origin + spacing * number);
        }
      }
    }

    function findRow(label, afterTop = -Infinity) {
      return lines.map(line => ({line, score:fuzzyPhraseScore(label, line.text)}))
        .filter(candidate => candidate.line.top > afterTop && candidate.score >= .62)
        .sort((left, right) => right.score - left.score)[0]?.line || null;
    }

    function rowValues(line) {
      if (!line) return new Map();
      const numericWords = line.words.map(word => {
        const values = numericValues(word.text);
        return values.length ? {word, value:values[values.length - 1], x:(word.x0 + word.x1) / 2} : null;
      }).filter(Boolean);
      const mapped = new Map();
      const channelXs = [...channelMap.entries()].sort((left, right) => left[0] - right[0]);
      if (channelXs.length >= 6) {
        const spacings = channelXs.slice(1).map((entry, index) => entry[1] - channelXs[index][1]).filter(value => value > 0);
        const spacing = spacings.sort((left, right) => left - right)[Math.floor(spacings.length / 2)] || 45;
        channelXs.filter(([number]) => number <= 17).forEach(([number, x]) => {
          const nearest = numericWords.map(entry => ({...entry, distance:Math.abs(entry.x - x)}))
            .filter(entry => entry.distance <= spacing * .52)
            .sort((left, right) => left.distance - right.distance)[0];
          if (nearest) mapped.set(number, {value:nearest.value, confidence:Math.round(Math.min(99, nearest.word.confidence || 0))});
        });
      }
      if (!mapped.size) {
        numericWords.sort((left, right) => left.x - right.x).slice(0, 17).forEach((entry, index) =>
          mapped.set(index + 1, {value:entry.value, confidence:Math.round(Math.min(99, entry.word.confidence || 0))}));
      }
      return mapped;
    }

    const setRow = findRow('Set Power');
    let standbyRow = findRow('Standby Power', setRow ? setRow.top : -Infinity);
    if (!standbyRow && setRow) {
      standbyRow = lines.filter(line => line.top > setRow.bottom && line.top - setRow.bottom < Math.max(80, (setRow.bottom - setRow.top) * 4)
        && line.words.filter(word => numericValues(word.text).length).length >= 6)[0] || null;
    }
    return {set:rowValues(setRow), standby:rowValues(standbyRow)};
  }

  function wordCenter(word) {
    return {x:(word.x0 + word.x1) / 2, y:(word.y0 + word.y1) / 2};
  }

  function bestHeaderWord(lines, label) {
    return lines.flatMap(line => line.words.map(word => ({word, score:fuzzyPhraseScore(label, word.text)})))
      .filter(candidate => candidate.score >= .76)
      .sort((left, right) => right.score - left.score || right.word.confidence - left.word.confidence)[0]?.word || null;
  }

  function ocrLabelAliases(label) {
    const clean = String(label || '').replace(/^Chamber\s+\d+\s*[·:-]\s*/i, '').trim();
    const aliases = [clean];
    const compactTemperature = clean.replace(/^Temperature\s+/i, 'Temp ');
    if (compactTemperature !== clean) aliases.push(compactTemperature);
    if (/^Upper Vacuum Time/i.test(clean)) aliases.push(clean.replace(/^Upper Vacuum Time/i, 'Upper vac. time'));
    if (/^Lower Vacuum Time/i.test(clean)) aliases.push(clean.replace(/^Lower Vacuum Time/i, 'Lower Vacuum Time'));
    if (/^Lower Vent Time/i.test(clean)) aliases.push(clean.replace(/^Lower Vent Time/i, 'Lower Vent Time'));
    return [...new Set(aliases)];
  }

  function bestLabelScore(label, text) {
    return Math.max(...ocrLabelAliases(label).map(alias => fuzzyPhraseScore(alias, text)));
  }

  function ocrLineText(line) {
    return line.text || (line.words || []).map(word => word.text).join(' ');
  }

  function isStringerTemperatureLabel(label) {
    const normal = normaliseOcrText(label);
    return stringerTemperatureLabels.some(candidate => normaliseOcrText(candidate) === normal);
  }

  // The Stringer temperature screen may be scanned as either the complete
  // Item/Actual/Lower/Set/Upper table or a narrow Item/Actual crop. Values are
  // therefore selected from the Actual column by X position and paired with
  // labels by row position. Digits inside labels (Drying Base 1-5, etc.) are
  // never eligible as readings.
  function stringerActualGrid(lines, labels) {
    const actualWord = bestHeaderWord(lines, 'Actual');
    if (!actualWord) return new Map();
    const actual = wordCenter(actualWord);
    const itemWord = bestHeaderWord(lines, 'Item');
    const minimumX = Math.min(...lines.flatMap(line => line.words.map(word => word.x0)), actualWord.x0);
    const maximumX = Math.max(...lines.flatMap(line => line.words.map(word => word.x1)), actualWord.x1);
    const pageWidth = Math.max(1, maximumX - minimumX);
    const headerY = actual.y;
    const nextHeader = lines.flatMap(line => line.words).map(word => ({word, center:wordCenter(word)}))
      .filter(candidate => candidate.center.x > actual.x && Math.abs(candidate.center.y - headerY) <= Math.max(18, actualWord.y1 - actualWord.y0))
      .sort((left, right) => left.center.x - right.center.x)[0];
    const columnLeft = itemWord && wordCenter(itemWord).x < actual.x
      ? (wordCenter(itemWord).x + actual.x) / 2
      : actual.x - pageWidth * .14;
    const columnRight = nextHeader
      ? (actual.x + nextHeader.center.x) / 2
      : Math.min(maximumX + 1, actual.x + Math.max(55, pageWidth * .18));
    const valueWords = lines.flatMap(line => line.words).flatMap(word => {
      const center = wordCenter(word);
      if (word.y0 <= actualWord.y1 || center.x <= columnLeft || center.x >= columnRight) return [];
      return numericValues(word.text).map(value => ({word, value, center}));
    });
    const readings = new Map();
    labels.forEach(label => {
      if (!isStringerTemperatureLabel(label)) return;
      const labelBox = phraseBox(lines.filter(line => line.bottom > actualWord.y1), label);
      if (!labelBox) return;
      const labelY = (labelBox.y0 + labelBox.y1) / 2;
      const rowHeight = Math.max(1, labelBox.y1 - labelBox.y0);
      const choices = valueWords.map(entry => ({
        ...entry,
        rowDistance:Math.abs(entry.center.y - labelY),
        columnDistance:Math.abs(entry.center.x - actual.x),
      })).filter(entry => entry.rowDistance <= Math.max(24, rowHeight * 1.35))
        .sort((left, right) => left.rowDistance - right.rowDistance || left.columnDistance - right.columnDistance);
      if (!choices.length) return;
      const chosen = choices[0];
      readings.set(label, {
        value:chosen.value,
        confidence:Math.round(Math.min(99, labelBox.score * 72 + Math.min(100, chosen.word.confidence) * .28)),
      });
    });
    return readings;
  }

  function phraseBox(lines, label) {
    let best;
    lines.forEach(line => {
      for (let start = 0; start < line.words.length; start += 1) {
        for (let end = start; end < Math.min(line.words.length, start + 3); end += 1) {
          const words = line.words.slice(start, end + 1);
          const text = words.map(word => word.text).join(' ');
          const score = fuzzyPhraseScore(label, text);
          if (score < .72) continue;
          const candidate = {
            score,
            x0:Math.min(...words.map(word => word.x0)), x1:Math.max(...words.map(word => word.x1)),
            y0:Math.min(...words.map(word => word.y0)), y1:Math.max(...words.map(word => word.y1)),
          };
          const candidateWidth = candidate.x1 - candidate.x0;
          const bestWidth = best ? best.x1 - best.x0 : Infinity;
          if (!best || candidate.score > best.score || (candidate.score === best.score && candidateWidth < bestWidth)) best = candidate;
        }
      }
    });
    return best || null;
  }

  function clippedOcrLines(lines, left, right) {
    return lines.map(line => {
      const words = line.words.filter(word => wordCenter(word).x >= left && wordCenter(word).x < right);
      if (!words.length) return null;
      return {
        words,
        text:words.map(word => word.text).join(' '),
        top:Math.min(...words.map(word => word.y0)), bottom:Math.max(...words.map(word => word.y1)),
      };
    }).filter(Boolean);
  }

  // The supplied Laminator HMI always presents Lam-1, Lam-2 and Lam-3 from
  // left to right. Each chamber contains two independent parameter/setting
  // blocks, so search each half separately and keep the best label match.
  function laminatorTemplateGrid(lines, labels) {
    const headings = [1, 2, 3].map(number => phraseBox(lines, `Lam ${number}`));
    if (headings.filter(Boolean).length < 2) return new Map();
    const knownCenters = headings.map(heading => heading ? (heading.x0 + heading.x1) / 2 : null);
    let spacing = knownCenters[1] && knownCenters[0] ? knownCenters[1] - knownCenters[0]
      : knownCenters[2] && knownCenters[1] ? knownCenters[2] - knownCenters[1] : 0;
    if (spacing <= 100) return new Map();
    if (!knownCenters[0]) knownCenters[0] = knownCenters[1] - spacing;
    if (!knownCenters[1]) knownCenters[1] = (knownCenters[0] + knownCenters[2]) / 2;
    if (!knownCenters[2]) knownCenters[2] = knownCenters[1] + spacing;
    spacing = ((knownCenters[1] - knownCenters[0]) + (knownCenters[2] - knownCenters[1])) / 2;

    const readings = new Map();
    labels.forEach(fullLabel => {
      const chamberMatch = String(fullLabel).match(/^Chamber\s+(\d+)\s*[·:-]\s*(.+)$/i);
      if (!chamberMatch) return;
      const chamber = Number(chamberMatch[1]);
      if (chamber < 1 || chamber > 3) return;
      const center = knownCenters[chamber - 1];
      const left = center - spacing * .52;
      const right = center + spacing * .52;
      // The first dark Setting box can cross the visual centre of a chamber,
      // so the two search windows deliberately overlap slightly.
      const halves = [clippedOcrLines(lines, left, center + spacing * .18), clippedOcrLines(lines, center + spacing * .02, right)];
      let best;
      ocrLabelAliases(chamberMatch[2]).forEach(alias => halves.forEach(half => {
        const found = findBestTableValue(alias, half);
        if (found && (!best || found.combinedScore > best.combinedScore)) best = found;
      }));
      if (!best) return;
      readings.set(fullLabel, {
        value:best.value,
        confidence:Math.round(Math.min(99, best.combinedScore * 100)),
      });
    });
    return readings;
  }

  function trailingTableCell(words) {
    if (!words.length) return [];
    const ordered = [...words].sort((left, right) => left.x0 - right.x0);
    const averageHeight = ordered.reduce((total, word) => total + Math.max(1, word.y1 - word.y0), 0) / ordered.length;
    const gapThreshold = Math.max(14, averageHeight * 1.35);
    let lastCellStart = 0;
    for (let index = 1; index < ordered.length; index += 1) {
      if (ordered[index].x0 - ordered[index - 1].x1 > gapThreshold) lastCellStart = index;
    }
    return ordered.slice(lastCellStart);
  }

  function tableCellValue(label, words) {
    const cell = trailingTableCell(words);
    if (!cell.length) return '';
    const text = cell.map(word => word.text).join(' ').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    if (/recipe|range/i.test(label)) return text.replace(/\s*[-–—]\s*/g, '-');
    const values = numericValues(text);
    return values.length ? values[values.length - 1] : text;
  }

  function findBestTableValue(label, lines, usedLines = new Set()) {
    let best;
    lines.forEach((line, lineIndex) => {
      if (usedLines.has(lineIndex)) return;
      const words = [...line.words].sort((left, right) => left.x0 - right.x0);
      const previous = lines[lineIndex - 1];
      const closePrevious = previous && line.top - previous.bottom < Math.max(22, (line.bottom - line.top) * 2.1);
      for (let split = 0; split < words.length; split += 1) {
        const prefix = words.slice(0, split).map(word => word.text).join(' ');
        const labelText = closePrevious ? `${previous.text} ${prefix}` : prefix;
        const score = Math.max(labelScore(label, prefix), labelScore(label, labelText));
        if (score < .62) continue;
        const valueWords = words.slice(split);
        const value = tableCellValue(label, valueWords);
        if (!value) continue;
        const valueCell = trailingTableCell(valueWords);
        const confidence = valueCell.reduce((total, word) => total + Math.min(100, word.confidence), 0) / Math.max(1, valueCell.length) / 100;
        const firstValue = valueCell[0];
        const lastLabel = words[split - 1];
        const gap = firstValue && lastLabel ? Math.max(0, firstValue.x0 - lastLabel.x1) : 0;
        const combinedScore = score * .82 + confidence * .13 + Math.min(.05, gap / 500);
        if (!best || combinedScore > best.combinedScore) best = {lineIndex, value, combinedScore, score};
      }
    });
    return best;
  }

  function targetMatches(control, selectedTarget) {
    if (!selectedTarget) return true;
    const target = normaliseOcrText(selectedTarget).replace(/\btrack\b/g, '').replace(/\s+/g, ' ').trim();
    const destination = normaliseOcrText(`${control.dataset.observationLabel || ''} ${control.dataset.fieldLabel || ''}`)
      .replace(/\btrack\b/g, '').replace(/\s+/g, ' ').trim();
    return destination.includes(target);
  }

  function buildOcrGroups(panel) {
    const scope = panel.dataset.photoImport;
    const step = panel.closest('.form-step');
    const selectedTarget = panel.querySelector('[data-photo-target]').value;
    const controls = [...step.querySelectorAll('[data-item-id][data-observation-index][data-parameter-label]')]
      .filter(control => !control.disabled && targetMatches(control, selectedTarget));
    const groups = new Map();
    controls.forEach(control => {
      const parameter = control.dataset.parameterLabel || '';
      const field = control.dataset.fieldLabel || '';
      let key; let label;
      if (scope === 'laminator') {
        key = `laminator:${field}`; label = field;
      } else {
        key = `parameter:${parameter}`; label = parameter;
      }
      if (!groups.has(key)) groups.set(key, {key, label, controls: []});
      groups.get(key).controls.push(control);
    });
    return [...groups.values()];
  }

  function findOcrCandidates(panel, ocrData) {
    const lines = mergeAlignedOcrLines(positionedOcrLines(ocrData));
    if (!lines.length) return {candidates: [], issue: 'no-table'};
    const candidates = []; const usedLines = new Set();
    const groups = buildOcrGroups(panel);
    const powerGrid = panel.dataset.photoImport === 'stringer' ? stringerPowerGrid(lines) : null;
    const hasActualColumn = panel.dataset.photoImport === 'stringer' && Boolean(bestHeaderWord(lines, 'Actual'));
    const actualGrid = panel.dataset.photoImport === 'stringer' ? stringerActualGrid(lines, groups.map(group => group.label)) : new Map();
    const laminatorGrid = panel.dataset.photoImport === 'laminator' ? laminatorTemplateGrid(lines, groups.map(group => group.label)) : new Map();
    groups.forEach(group => {
      if (group.controls.length !== 1) return;
      const powerMatch = group.label.match(/^(Set Power|Standby Power)\s*#\s*(\d+)$/i);
      if (powerMatch && powerGrid) {
        const source = /^set/i.test(powerMatch[1]) ? powerGrid.set : powerGrid.standby;
        const reading = source.get(Number(powerMatch[2]));
        if (!reading) return;
        const control = group.controls[0];
        candidates.push({
          control, value:reading.value, parameter:group.label,
          destination:control.dataset.observationLabel || control.dataset.fieldLabel || 'Matrix field',
          confidence:reading.confidence,
        });
        return;
      }
      const templateReading = actualGrid.get(group.label) || laminatorGrid.get(group.label);
      if (templateReading) {
        const control = group.controls[0];
        candidates.push({
          control, value:templateReading.value, parameter:group.label,
          destination:control.dataset.observationLabel || control.dataset.fieldLabel || 'Matrix field',
          confidence:templateReading.confidence,
        });
        return;
      }
      // When an Actual-column screen is recognised, never fall back to the
      // generic row parser for its temperature labels: that parser could
      // mistake the 2 in "Drying Base 2" for the measured value.
      if (hasActualColumn && isStringerTemperatureLabel(group.label)) return;
      const best = findBestTableValue(group.label, lines, usedLines);
      if (!best) return;
      usedLines.add(best.lineIndex);
      const control = group.controls[0];
      candidates.push({
        control, value: best.value, parameter: group.label,
        destination: control.dataset.observationLabel || control.dataset.fieldLabel || 'Matrix field',
        confidence: Math.round(Math.min(99, best.combinedScore * 100)),
      });
    });
    return {candidates, issue: candidates.length ? '' : 'no-matches'};
  }

  function applyFixedStringerReadings(panel, detection, readings) {
    if (readings.size < 6) return detection;
    const candidates = detection.candidates.filter(candidate => !isStringerTemperatureLabel(candidate.parameter));
    buildOcrGroups(panel).forEach(group => {
      if (group.controls.length !== 1 || !readings.has(group.label)) return;
      const reading = readings.get(group.label); const control = group.controls[0];
      candidates.push({
        control, value:reading.value, parameter:group.label,
        destination:control.dataset.observationLabel || control.dataset.fieldLabel || 'Matrix field',
        confidence:reading.confidence,
      });
    });
    return {candidates, issue:candidates.length ? '' : detection.issue};
  }

  function applyOcrValue(control, value) {
    const clean = String(value || '').trim();
    if (control.tagName === 'SELECT') {
      const option = [...control.options].find(candidate => normaliseOcrText(candidate.value) === normaliseOcrText(clean));
      if (!option) return false;
      control.value = option.value;
      syncMaterialChoice(control);
    } else {
      control.value = clean.slice(0, Number(control.maxLength) > 0 ? Number(control.maxLength) : 500);
    }
    control.dispatchEvent(new Event('input', {bubbles: true}));
    control.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }

  document.querySelectorAll('[data-photo-import]').forEach(panel => {
    const input = panel.querySelector('[data-photo-input]');
    const workspace = panel.querySelector('[data-photo-workspace]');
    const preview = panel.querySelector('[data-photo-preview]');
    const status = panel.querySelector('[data-photo-status]');
    const progress = panel.querySelector('[data-photo-progress]');
    const summary = panel.querySelector('[data-photo-summary]');
    const results = panel.querySelector('[data-photo-results]');
    const pasteButton = panel.querySelector('[data-photo-paste]');
    let objectUrl; let candidates = [];

    function discard() {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = ''; candidates = []; input.value = ''; preview.removeAttribute('src');
      results.replaceChildren(); workspace.hidden = true; pasteButton.disabled = true;
      progress.value = 0; summary.textContent = '';
    }

    function renderCandidates(found) {
      results.replaceChildren();
      found.forEach((candidate, index) => {
        const row = document.createElement('label');
        row.className = 'photo-result-row';
        row.innerHTML = `<input type="checkbox" checked data-photo-use="${index}"><span><strong></strong><small></small></span><input type="text" maxlength="40" data-photo-value="${index}"><em></em>`;
        row.querySelector('strong').textContent = candidate.parameter;
        row.querySelector('small').textContent = candidate.destination;
        row.querySelector('[data-photo-value]').value = candidate.value;
        row.querySelector('em').textContent = `${candidate.confidence}% match`;
        row.dataset.confidence = candidate.confidence >= 75 ? 'high' : 'review';
        results.append(row);
      });
      pasteButton.disabled = !found.length;
    }

    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return;
      if (!panel.querySelector('[data-photo-target]').value) {
        showGridNotice('Select the Stringer or Laminator shown in the PDF first.', 'warning'); discard(); return;
      }
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      if (!isPdf) { showGridNotice('Select a PDF created by the document scanner.', 'warning'); discard(); return; }
      if (file.size > 25 * 1024 * 1024) { showGridNotice('PDF must be smaller than 25 MB.', 'warning'); discard(); return; }
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = ''; preview.removeAttribute('src'); workspace.hidden = false;
      candidates = []; renderCandidates([]); status.textContent = 'Rendering the first PDF page securely…'; summary.textContent = 'The PDF is processed temporarily and is not saved.'; progress.value = 1;
      let worker;
      try {
        const renderedPage = await renderPdfFirstPage(file);
        objectUrl = URL.createObjectURL(renderedPage); preview.src = objectUrl;
        const Tesseract = await loadOcrEngine();
        worker = await Tesseract.createWorker('eng', 1, {logger(message) {
          if (message.status) status.textContent = message.status.replace(/\b\w/g, character => character.toUpperCase());
          if (Number.isFinite(message.progress)) progress.value = Math.round(message.progress * 100);
        }});
        status.textContent = 'Enhancing the scanned PDF page…';
        const ocrPhoto = await prepareOcrPhoto(renderedPage);
        await worker.setParameters({tessedit_pageseg_mode:'4', preserve_interword_spaces:'1'});
        status.textContent = 'Detecting PDF page direction…';
        const recognition = await worker.recognize(ocrPhoto, {rotateAuto: true}, {blocks: true});
        let detection = findOcrCandidates(panel, recognition.data);
        if (panel.dataset.photoImport === 'stringer') {
          status.textContent = 'Reading the Actual value cells…';
          const fixedReadings = await readStringerActualCells(renderedPage, worker);
          detection = applyFixedStringerReadings(panel, detection, fixedReadings);
        }
        candidates = detection.candidates;
        renderCandidates(candidates);
        progress.value = 100;
        status.textContent = candidates.length ? 'Review detected table values' : detection.issue === 'no-table' ? 'Table could not be read' : 'No reliable table values found';
        summary.textContent = candidates.length
          ? `${candidates.length} table value${candidates.length === 1 ? '' : 's'} matched from the first PDF page after automatic orientation correction. Correct or untick doubtful values before pasting.`
          : detection.issue === 'no-table'
            ? 'No readable table rows were found. Rescan the complete machine screen clearly and upload a one-page PDF.'
            : 'Keep the parameter names and their values clearly visible in the first PDF page; any page direction is supported.';
      } catch (error) {
        status.textContent = 'PDF reading failed'; summary.textContent = `${error.message}. Rescan the page clearly or reload and try again.`;
        progress.value = 0; showGridNotice('The scanned PDF could not be decoded.', 'warning');
      } finally {
        if (worker) await worker.terminate().catch(() => {});
      }
    });

    panel.querySelector('[data-photo-discard]').addEventListener('click', discard);
    pasteButton.addEventListener('click', () => {
      const selected = [...results.querySelectorAll('[data-photo-use]:checked')].map(box => Number(box.dataset.photoUse));
      if (!selected.length) { showGridNotice('Select at least one detected value.', 'warning'); return; }
      const conflicts = selected.filter(index => candidates[index].control.value.trim() && candidates[index].control.value.trim() !== results.querySelector(`[data-photo-value="${index}"]`).value.trim()).length;
      if (conflicts && !window.confirm(`${conflicts} selected field${conflicts === 1 ? '' : 's'} already contain data. Replace those values?`)) return;
      let pasted = 0;
      selected.forEach(index => {
        const value = results.querySelector(`[data-photo-value="${index}"]`).value;
        if (applyOcrValue(candidates[index].control, value)) pasted += 1;
      });
      showGridNotice(`${pasted} reviewed value${pasted === 1 ? '' : 's'} pasted into the matrix.`);
      updateSummary(); discard();
    });
  });

  document.querySelectorAll('[data-ctq-pdf-import]').forEach(panel => {
    const input = panel.querySelector('[data-ctq-pdf-input]');
    const workspace = panel.querySelector('[data-ctq-pdf-workspace]');
    const preview = panel.querySelector('[data-ctq-pdf-preview]');
    const status = panel.querySelector('[data-ctq-pdf-status]');
    const progress = panel.querySelector('[data-ctq-pdf-progress]');
    const summary = panel.querySelector('[data-ctq-pdf-summary]');
    const results = panel.querySelector('[data-ctq-pdf-results]');
    const pasteButton = panel.querySelector('[data-ctq-pdf-paste]');
    let objectUrl = ''; let candidates = [];

    function discard() {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = ''; candidates = []; input.value = ''; preview.removeAttribute('src');
      results.replaceChildren(); workspace.hidden = true; pasteButton.disabled = true;
      progress.value = 0; summary.textContent = '';
    }

    function renderCandidates(found) {
      results.replaceChildren();
      found.forEach((candidate, index) => {
        const row = document.createElement('label');
        row.className = 'photo-result-row';
        row.innerHTML = `<input type="checkbox" checked data-ctq-pdf-use="${index}"><span><strong></strong><small></small></span><input type="text" maxlength="500" data-ctq-pdf-value="${index}"><em></em>`;
        row.querySelector('strong').textContent = candidate.label;
        row.querySelector('small').textContent = 'Controlled CTQ field';
        row.querySelector('[data-ctq-pdf-value]').value = candidate.value;
        row.querySelector('em').textContent = `${candidate.confidence}% match`;
        row.dataset.confidence = candidate.confidence >= 75 ? 'high' : 'review';
        results.append(row);
      });
      pasteButton.disabled = !found.length;
    }

    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return;
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      if (!isPdf) { showGridNotice('Select a PDF created by the document scanner.', 'warning'); discard(); return; }
      if (file.size > 25 * 1024 * 1024) { showGridNotice('PDF must be smaller than 25 MB.', 'warning'); discard(); return; }
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = ''; candidates = []; preview.removeAttribute('src'); workspace.hidden = false;
      renderCandidates([]); progress.value = 1; status.textContent = 'Rendering the first PDF page securely…';
      summary.textContent = 'The PDF is processed temporarily and is not saved.';
      let worker;
      try {
        const renderedPage = await renderPdfFirstPage(file);
        objectUrl = URL.createObjectURL(renderedPage); preview.src = objectUrl;
        const Tesseract = await loadOcrEngine();
        worker = await Tesseract.createWorker('eng', 1, {logger(message) {
          if (message.status) status.textContent = message.status.replace(/\b\w/g, character => character.toUpperCase());
          if (Number.isFinite(message.progress)) progress.value = Math.round(message.progress * 100);
        }});
        const ocrPhoto = await prepareOcrPhoto(renderedPage);
        await worker.setParameters({tessedit_pageseg_mode:'4', preserve_interword_spaces:'1'});
        const recognition = await worker.recognize(ocrPhoto, {rotateAuto:true}, {blocks:true});
        const lines = mergeAlignedOcrLines(positionedOcrLines(recognition.data));
        const usedLines = new Set();
        const fields = [...panel.parentElement.querySelectorAll('[data-ctq-field][data-ctq-label]')]
          .filter(control => control.type !== 'checkbox' && !control.disabled);
        const ctqKind = panel.parentElement.querySelector('[data-ctq-form]')?.dataset.ctqKind;
        const gelLaminatorGrid = ctqKind === 'gel'
          ? laminatorTemplateGrid(lines, fields.map(control => control.dataset.ctqLabel))
          : new Map();
        fields.forEach(control => {
          const templateReading = gelLaminatorGrid.get(control.dataset.ctqLabel);
          if (templateReading) {
            candidates.push({
              control, value:templateReading.value, label:control.dataset.ctqLabel,
              confidence:templateReading.confidence,
            });
            return;
          }
          let best;
          ocrLabelAliases(control.dataset.ctqLabel).forEach(alias => {
            const found = findBestTableValue(alias, lines, usedLines);
            if (found && (!best || found.combinedScore > best.combinedScore)) best = found;
          });
          if (!best) return;
          usedLines.add(best.lineIndex);
          candidates.push({
            control, value:best.value, label:control.dataset.ctqLabel,
            confidence:Math.round(Math.min(99, best.combinedScore * 100)),
          });
        });
        renderCandidates(candidates); progress.value = 100;
        status.textContent = candidates.length ? 'Review detected PDF values' : 'No reliable field matches found';
        summary.textContent = candidates.length
          ? `${candidates.length} value${candidates.length === 1 ? '' : 's'} matched. Correct or untick doubtful values before pasting.`
          : 'The upload control is ready. Once you provide the representative test PDFs, their fixed layouts can be mapped for higher accuracy.';
      } catch (error) {
        status.textContent = 'PDF reading failed'; summary.textContent = `${error.message}. Rescan clearly or reload and try again.`;
        progress.value = 0; showGridNotice('The CTQ PDF could not be decoded.', 'warning');
      } finally {
        if (worker) await worker.terminate().catch(() => {});
      }
    });

    panel.querySelector('[data-ctq-pdf-discard]').addEventListener('click', discard);
    pasteButton.addEventListener('click', () => {
      const selected = [...results.querySelectorAll('[data-ctq-pdf-use]:checked')].map(box => Number(box.dataset.ctqPdfUse));
      if (!selected.length) { showGridNotice('Select at least one detected value.', 'warning'); return; }
      const conflicts = selected.filter(index => {
        const controlValue = materialControlValue(candidates[index].control).trim();
        const detected = results.querySelector(`[data-ctq-pdf-value="${index}"]`).value.trim();
        return controlValue && controlValue !== detected;
      }).length;
      if (conflicts && !window.confirm(`${conflicts} selected field${conflicts === 1 ? '' : 's'} already contain data. Replace those values?`)) return;
      let pasted = 0;
      selected.forEach(index => {
        const value = results.querySelector(`[data-ctq-pdf-value="${index}"]`).value;
        if (applyOcrValue(candidates[index].control, value)) pasted += 1;
      });
      showGridNotice(`${pasted} reviewed PDF value${pasted === 1 ? '' : 's'} pasted into the test form.`);
      updateSummary(); discard();
    });
  });

  function writeClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    const helper = document.createElement('textarea');
    helper.value = text;
    helper.setAttribute('readonly', '');
    helper.style.position = 'fixed';
    helper.style.opacity = '0';
    document.body.append(helper);
    helper.select();
    const copied = document.execCommand('copy');
    helper.remove();
    return copied ? Promise.resolve() : Promise.reject(new Error('Clipboard copy failed'));
  }

  function enhanceEntryMatrix(table) {
    const rows = [...table.tBodies].flatMap(body => [...body.rows]).map((row, rowIndex) =>
      [...row.querySelectorAll('td')].map((cell, columnIndex) => {
        const control = cell.querySelector('input:not([type="hidden"]), select, textarea');
        if (!control) return null;
        control.dataset.gridRow = String(rowIndex);
        control.dataset.gridColumn = String(columnIndex);
        control.autocomplete = 'off';
        cell.dataset.gridCell = '';
        return control;
      })
    );
    const controls = rows.flat().filter(Boolean);
    if (!controls.length) return;
    const state = {anchor: controls[0], focus: controls[0], suppressFocus: false};

    function controlAt(row, column) {
      return rows[row]?.[column] || null;
    }
    function coordinates(control) {
      return [Number(control.dataset.gridRow), Number(control.dataset.gridColumn)];
    }
    function selectedControls() {
      return controls.filter(control => control.closest('td').classList.contains('grid-selected'));
    }
    function selectRange(anchor, focus, moveFocus = false) {
      const [aRow, aColumn] = coordinates(anchor);
      const [fRow, fColumn] = coordinates(focus);
      const minRow = Math.min(aRow, fRow); const maxRow = Math.max(aRow, fRow);
      const minColumn = Math.min(aColumn, fColumn); const maxColumn = Math.max(aColumn, fColumn);
      controls.forEach(control => {
        const [row, column] = coordinates(control);
        const selected = row >= minRow && row <= maxRow && column >= minColumn && column <= maxColumn;
        control.closest('td').classList.toggle('grid-selected', selected);
        control.closest('td').classList.toggle('grid-active', control === focus);
      });
      state.focus = focus;
      if (moveFocus) {
        state.suppressFocus = true;
        focus.focus({preventScroll: true});
        focus.scrollIntoView({block: 'nearest', inline: 'nearest'});
      }
    }
    function selectSingle(control) {
      state.anchor = control;
      selectRange(control, control);
    }
    function move(control, rowDelta, columnDelta, extend = false) {
      const [row, column] = coordinates(control);
      let target = controlAt(row + rowDelta, column + columnDelta);
      if (!target && rowDelta) {
        const targetRow = rows[row + rowDelta] || [];
        target = targetRow[column] || targetRow.filter(Boolean).at(-1);
      }
      if (!target && columnDelta) {
        const wrappedRow = rows[row + (columnDelta > 0 ? 1 : -1)] || [];
        const available = wrappedRow.filter(Boolean);
        target = columnDelta > 0 ? available[0] : available.at(-1);
      }
      if (!target) return;
      if (!extend) state.anchor = target;
      selectRange(state.anchor, target, true);
    }
    function setValue(control, value) {
      const clean = value.trim();
      if (control.tagName === 'SELECT') {
        const option = [...control.options].find(candidate => candidate.value.trim().toLocaleLowerCase() === clean.toLocaleLowerCase());
        if (!option && clean && control.matches('[data-material-select]')) {
          control.value = '__other__';
          syncMaterialChoice(control);
          const manual = control.closest('[data-material-choice]')?.querySelector('[data-material-other]');
          if (manual) manual.value = clean.slice(0, 500);
        } else {
          if (!option && clean) return false;
          control.value = option ? option.value : '';
          syncMaterialChoice(control);
        }
      } else {
        control.value = clean.slice(0, Number(control.maxLength) > 0 ? Number(control.maxLength) : undefined);
      }
      control.dispatchEvent(new Event('input', {bubbles: true}));
      control.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
    function parseClipboard(text) {
      const parsed = text.replace(/\r/g, '').split('\n').map(row => row.split('\t'));
      while (parsed.length > 1 && parsed.at(-1).every(value => value === '')) parsed.pop();
      return parsed;
    }
    function pasteTable(text, start = state.focus) {
      const values = parseClipboard(text);
      if (!values.length || !start) return;
      const [startRow, startColumn] = coordinates(start);
      let pasted = 0; let skipped = 0;
      values.forEach((clipboardRow, rowOffset) => clipboardRow.forEach((value, columnOffset) => {
        const target = controlAt(startRow + rowOffset, startColumn + columnOffset);
        if (!target) { skipped += 1; return; }
        if (setValue(target, value)) pasted += 1; else skipped += 1;
      }));
      const lastRow = Math.min(rows.length - 1, startRow + values.length - 1);
      const lastColumn = Math.min((rows[lastRow] || []).length - 1, startColumn + Math.max(...values.map(row => row.length)) - 1);
      const last = controlAt(lastRow, lastColumn) || start;
      selectRange(start, last, true);
      showGridNotice(skipped ? `Pasted ${pasted} cells; ${skipped} cells were outside the table or invalid dropdown values.` : `Pasted ${pasted} cells.`, skipped ? 'warning' : 'success');
    }
    function selectionText() {
      const selected = selectedControls();
      if (!selected.length) return state.focus ? materialControlValue(state.focus) : '';
      const positions = selected.map(coordinates);
      const minRow = Math.min(...positions.map(position => position[0]));
      const maxRow = Math.max(...positions.map(position => position[0]));
      const minColumn = Math.min(...positions.map(position => position[1]));
      const maxColumn = Math.max(...positions.map(position => position[1]));
      return Array.from({length: maxRow - minRow + 1}, (_, rowOffset) =>
        Array.from({length: maxColumn - minColumn + 1}, (_, columnOffset) =>
          controlAt(minRow + rowOffset, minColumn + columnOffset) ? materialControlValue(controlAt(minRow + rowOffset, minColumn + columnOffset)) : ''
        ).join('\t')
      ).join('\n');
    }
    function copySelection() {
      writeClipboard(selectionText())
        .then(() => showGridNotice(`Copied ${selectedControls().length || 1} cell${(selectedControls().length || 1) === 1 ? '' : 's'}.`))
        .catch(() => showGridNotice('Copy was blocked by the browser. Use Ctrl+C from the selected cell.', 'warning'));
    }

    controls.forEach(control => {
      control.addEventListener('pointerdown', event => {
        if (!event.shiftKey || !state.anchor) return;
        event.preventDefault();
        selectRange(state.anchor, control, true);
      });
      control.addEventListener('focus', () => {
        if (state.suppressFocus) { state.suppressFocus = false; return; }
        selectSingle(control);
      });
      control.addEventListener('keydown', event => {
        if (event.altKey && control.tagName === 'SELECT') return;
        const extend = event.shiftKey;
        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
          event.preventDefault(); move(control, event.key === 'ArrowUp' ? -1 : 1, 0, extend); return;
        }
        if (event.key === 'Enter') {
          event.preventDefault(); move(control, event.shiftKey ? -1 : 1, 0); return;
        }
        if (event.key === 'ArrowLeft') {
          event.preventDefault(); move(control, 0, -1, extend); return;
        }
        if (event.key === 'ArrowRight') {
          event.preventDefault(); move(control, 0, 1, extend);
        }
      });
      control.addEventListener('paste', event => {
        const text = event.clipboardData?.getData('text/plain') || '';
        if (text.includes('\t') || text.includes('\n') || control.tagName === 'SELECT' || selectedControls().length > 1) {
          event.preventDefault();
          if (!text.includes('\t') && !text.includes('\n') && selectedControls().length > 1) {
            let pasted = 0; let skipped = 0;
            selectedControls().forEach(selected => setValue(selected, text) ? pasted += 1 : skipped += 1);
            showGridNotice(skipped ? `Filled ${pasted} cells; ${skipped} dropdown values were invalid.` : `Filled ${pasted} selected cells.`, skipped ? 'warning' : 'success');
          } else pasteTable(text, control);
        }
      });
    });
    table.addEventListener('copy', event => {
      if (!event.clipboardData) return;
      const active = document.activeElement;
      const partialTextSelected = active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA') &&
        active.selectionStart !== null && active.selectionStart !== active.selectionEnd;
      if (selectedControls().length <= 1 && partialTextSelected) return;
      event.preventDefault();
      event.clipboardData.setData('text/plain', selectionText());
      showGridNotice(`Copied ${selectedControls().length || 1} cell${(selectedControls().length || 1) === 1 ? '' : 's'}.`);
    });

    const scroll = table.closest('.matrix-scroll');
    const host = scroll?.parentElement;
    if (!host || !scroll) return;
    const tools = document.createElement('div');
    tools.className = 'matrix-tools';
    tools.innerHTML = '<span>Click a cell · Shift-click to select a range · paste Excel cells directly</span><div><button type="button" data-grid-copy>Copy selection</button><button type="button" data-grid-paste>Paste table</button><button type="button" data-grid-clear>Clear cells</button></div>';
    host.insertBefore(tools, scroll);
    const pastePanel = document.createElement('div');
    pastePanel.className = 'table-paste-panel';
    pastePanel.hidden = true;
    pastePanel.innerHTML = '<label>Paste rows and columns copied from Excel or another table<textarea rows="4" data-grid-paste-text placeholder="Paste tab-separated cells here"></textarea></label><div><button type="button" data-grid-apply>Apply to table</button><button type="button" data-grid-cancel>Cancel</button></div>';
    host.insertBefore(pastePanel, scroll);
    tools.querySelector('[data-grid-copy]').addEventListener('click', copySelection);
    tools.querySelector('[data-grid-clear]').addEventListener('click', () => {
      const selected = selectedControls();
      if (!selected.length) { showGridNotice('Select one or more cells first.', 'warning'); return; }
      if (!window.confirm(`Clear ${selected.length} selected cell${selected.length === 1 ? '' : 's'}?`)) return;
      selected.forEach(control => setValue(control, ''));
      showGridNotice(`${selected.length} selected cell${selected.length === 1 ? '' : 's'} cleared.`);
    });
    tools.querySelector('[data-grid-paste]').addEventListener('click', () => {
      pastePanel.hidden = false;
      pastePanel.querySelector('[data-grid-paste-text]').focus();
    });
    pastePanel.querySelector('[data-grid-cancel]').addEventListener('click', () => {
      pastePanel.hidden = true;
      pastePanel.querySelector('[data-grid-paste-text]').value = '';
      state.focus.focus({preventScroll: true});
    });
    pastePanel.querySelector('[data-grid-apply]').addEventListener('click', () => {
      const pasteText = pastePanel.querySelector('[data-grid-paste-text]');
      if (!pasteText.value) { showGridNotice('Paste table data into the box first.', 'warning'); return; }
      pasteTable(pasteText.value);
      pasteText.value = '';
      pastePanel.hidden = true;
    });
  }

  form.querySelectorAll('.stringer-matrix').forEach(table => {
    if (!table.closest('[data-ctq-form]')) enhanceEntryMatrix(table);
  });

  function enhanceObservationArrowNavigation() {
    const observationSelector = '[data-item-id][data-observation-index], [data-generic-cell], [data-ctq-field]';
    function visibleControls(step) {
      return [...step.querySelectorAll(observationSelector)].filter(control =>
        !control.disabled && control.getClientRects().length && !control.closest('.stringer-matrix')
      );
    }
    function focusControl(control) {
      control.focus({preventScroll: true});
      control.scrollIntoView({block: 'nearest', inline: 'nearest'});
      if (control.tagName === 'INPUT' && typeof control.select === 'function') control.select();
    }
    function spatialTarget(current, controls, direction) {
      const currentRect = current.getBoundingClientRect();
      const currentX = currentRect.left + currentRect.width / 2;
      const currentY = currentRect.top + currentRect.height / 2;
      const horizontal = direction === 'left' || direction === 'right';
      const sign = direction === 'left' || direction === 'up' ? -1 : 1;
      const candidates = controls.filter(control => {
        if (control === current) return false;
        const rect = control.getBoundingClientRect();
        const delta = horizontal
          ? rect.left + rect.width / 2 - currentX
          : rect.top + rect.height / 2 - currentY;
        return delta * sign > 4;
      });
      candidates.sort((first, second) => {
        const firstRect = first.getBoundingClientRect();
        const secondRect = second.getBoundingClientRect();
        const firstX = firstRect.left + firstRect.width / 2; const firstY = firstRect.top + firstRect.height / 2;
        const secondX = secondRect.left + secondRect.width / 2; const secondY = secondRect.top + secondRect.height / 2;
        const firstScore = horizontal ? Math.abs(firstX - currentX) + Math.abs(firstY - currentY) * 4 : Math.abs(firstY - currentY) + Math.abs(firstX - currentX) * 2;
        const secondScore = horizontal ? Math.abs(secondX - currentX) + Math.abs(secondY - currentY) * 4 : Math.abs(secondY - currentY) + Math.abs(secondX - currentX) * 2;
        return firstScore - secondScore;
      });
      return candidates[0] || null;
    }
    form.addEventListener('keydown', event => {
      if (event.defaultPrevented || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
      const current = event.target.closest?.(observationSelector);
      if (!current || current.closest('.stringer-matrix')) return;
      if (event.altKey && current.tagName === 'SELECT') return;
      const step = current.closest('[data-form-step]');
      if (!step) return;
      const controls = visibleControls(step);
      const index = controls.indexOf(current);
      if (index < 0) return;
      const direction = event.key.replace('Arrow', '').toLowerCase();
      let target = spatialTarget(current, controls, direction);
      if (!target && direction === 'right') target = controls[index + 1] || controls[0];
      if (!target && direction === 'left') target = controls[index - 1] || controls.at(-1);
      if (!target && direction === 'down') target = controls[index + 1] || null;
      if (!target && direction === 'up') target = controls[index - 1] || null;
      if (!target || target === current) return;
      event.preventDefault();
      focusControl(target);
    });
  }
  enhanceObservationArrowNavigation();
  const steps = [...document.querySelectorAll('[data-form-step]')];
  const pills = [...document.querySelectorAll('[data-step-jump]')];
  let current = 0;
  function show(index) {
    current = Math.max(0, Math.min(index, steps.length - 1));
    steps.forEach((step, i) => step.classList.toggle('active', i === current));
    pills.forEach((pill, i) => pill.classList.toggle('active', i === current));
    pills[current]?.scrollIntoView({behavior:'smooth', block:'nearest', inline:'center'});
    if (current === steps.length - 1) updateSummary();
    window.scrollTo({top: 0, behavior: 'smooth'});
  }
  document.querySelectorAll('[data-next]').forEach(button => button.addEventListener('click', () => show(current + 1)));
  document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => show(current - 1)));
  pills.forEach(button => button.addEventListener('click', () => show(Number(button.dataset.stepJump))));

  const genericHost = document.querySelector('#generic-rows');
  const ctqHost = document.querySelector('[data-ctq-form]');
  let genericRows = [];
  let genericLabels = [];
  function make(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function renderGeneric() {
    if (!genericHost) return;
    genericHost.replaceChildren();
    genericRows.forEach((row, index) => {
      const card = make('article', undefined, 'generic-row');
      card.append(make('h3', `Reading ${index + 1}`));
      if (genericRows.length > 1) {
        const remove = make('button', 'Remove', 'remove-row'); remove.type = 'button';
        remove.addEventListener('click', () => { genericRows.splice(index, 1); renderGeneric(); }); card.append(remove);
      }
      const grid = make('div', undefined, 'generic-row-grid');
      [...genericLabels, 'Result'].forEach(labelText => {
        const label = make('label', labelText);
        let field;
        if (labelText === 'Result') {
          field = document.createElement('select');
          ['Not evaluated','PASS','FAIL'].forEach(value => { const option=make('option',value);option.value=value;option.selected=row.Result===value;field.append(option); });
        } else {
          field = document.createElement('input'); field.maxLength=500; field.value=row[labelText] || '';
        }
        field.dataset.genericCell = '';
        field.addEventListener('input', () => { row[labelText] = field.value; });
        field.addEventListener('change', () => { row[labelText] = field.value; });
        label.append(field); grid.append(label);
      });
      card.append(grid); genericHost.append(card);
    });
    const counter=document.querySelector('#row-count'); if(counter) counter.textContent=`${genericRows.length} ${genericRows.length===1?'row':'rows'}`;
  }
  if (genericHost) {
    genericLabels=JSON.parse(genericHost.dataset.labels); genericRows=JSON.parse(genericHost.dataset.rows);
    renderGeneric();
    document.querySelector('[data-add-row]')?.addEventListener('click', () => {
      const row={Result:'Not evaluated'}; genericLabels.forEach(label=>row[label]=''); genericRows.push(row); renderGeneric();
    });
  }

  function collectCtq() {
    const values = {};
    ctqHost?.querySelectorAll('[data-ctq-field]').forEach(field => {
      values[field.dataset.ctqField] = field.type === 'checkbox' ? (field.checked ? '1' : '') : materialControlValue(field);
    });
    return {format: 'ctq-v1', values};
  }

  function updateCtqCalculations() {
    if (!ctqHost) return;
    const kind = ctqHost.dataset.ctqKind;
    const peelDivisorMm = 0.24;
    const values = collectCtq().values;
    const number = key => {
      const value = values[key];
      if (value === '' || value === undefined) return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const showNumber = value => Number.isFinite(value) ? Number(value.toFixed(3)).toString() : '—';
    const setCalculation = (key, value) => {
      const output = ctqHost.querySelector(`[data-ctq-calc="${key}"]`);
      if (output) output.textContent = value === null || value === undefined ? '—' : showNumber(value);
    };
    let assessment = 'Pending';
    if (kind === 'gel') {
      const gels = [];
      for (let sample = 1; sample <= ctqHost.querySelectorAll('[data-ctq-field$="_w1"]').length; sample += 1) {
        const w1 = number(`sample_${sample}_w1`); const w2 = number(`sample_${sample}_w2`); const w3 = number(`sample_${sample}_w3`);
        const dried = w2 !== null && w3 !== null && w3 >= w2 ? w3 - w2 : null;
        const gel = dried !== null && w1 !== null && w1 > 0 ? dried / w1 * 100 : null;
        setCalculation(`sample_${sample}_dried`, dried); setCalculation(`sample_${sample}_gel`, gel);
        if (gel !== null) gels.push(gel);
      }
      const average = gels.length ? gels.reduce((total, value) => total + value, 0) / gels.length : null;
      setCalculation('average_gel', average);
      if (gels.length === ctqHost.querySelectorAll('[data-ctq-field$="_w1"]').length) assessment = average >= 75 && average <= 95 ? 'PASS' : 'FAIL';
    } else if (kind === 'ribbon_peel') {
      const positionRows = [...ctqHost.querySelectorAll('[data-ribbon-position]')];
      const outcomes = [];
      let completeCount = 0;
      positionRows.forEach(row => {
        const minimum = Number(row.dataset.ribbonMinimum);
        const prefix = row.dataset.ribbonCalcPrefix;
        const peakInputs = [...row.querySelectorAll('[data-ribbon-peak]')];
        const readings = peakInputs.map(input => number(input.dataset.ctqField));
        peakInputs.forEach((input, index) => {
          input.closest('td')?.classList.toggle(
            'ribbon-below-limit', readings[index] !== null && readings[index] < minimum
          );
        });
        const complete = readings.length > 0 && readings.every(value => value !== null);
        if (!complete) {
          setCalculation(`${prefix}_average`, null);
          setCalculation(`${prefix}_n_per_mm`, null);
          return;
        }
        completeCount += 1;
        const average = readings.reduce((total, value) => total + value, 0) / readings.length;
        setCalculation(`${prefix}_average`, average);
        setCalculation(`${prefix}_n_per_mm`, average / peelDivisorMm);
        outcomes.push(readings.every(value => value >= minimum));
      });
      if (positionRows.length && completeCount === positionRows.length) {
        assessment = outcomes.every(Boolean) ? 'PASS' : 'FAIL';
      }
    } else if (kind === 'adhesion') {
      const outcomes = [];
      [['glass', 60], ['backsheet', 40]].forEach(([group, minimum]) => {
        const readings = Array.from({length: ctqHost.querySelectorAll(`[data-ctq-field^="${group}_"]`).length}, (_, index) => number(`${group}_${index + 1}`));
        const complete = readings.every(value => value !== null);
        const average = complete ? readings.reduce((total, value) => total + value, 0) / readings.length : null;
        setCalculation(`${group}_average`, average);
        if (complete) outcomes.push(average >= minimum);
      });
      if (outcomes.length === 2) assessment = outcomes.every(Boolean) ? 'PASS' : 'FAIL';
    } else if (kind === 'busbar_peel') {
      const outcomes = [];
      let activeCount = 0; let completeCount = 0;
      ['long', 'short', 'top', 'bottom'].forEach(prefix => {
        const row = ctqHost.querySelector(`[data-busbar-row="${prefix}"]`);
        const readings = Array.from({length: row?.querySelectorAll('[data-ctq-field]:not([type=checkbox])').length || 0}, (_, index) => number(`${prefix}_r${index + 1}`));
        const active = values[`${prefix}_enabled`] === '1' || readings.some(value => value !== null);
        row?.classList.toggle('inactive', !active);
        const complete = active && readings.every(value => value !== null);
        if (active) activeCount += 1;
        if (complete) {
          completeCount += 1;
          const average = readings.reduce((total, value) => total + value, 0) / readings.length;
          setCalculation(`${prefix}_average`, average);
          setCalculation(`${prefix}_n_per_mm`, average / peelDivisorMm);
          outcomes.push(readings.every(value => value >= 2));
        } else {
          setCalculation(`${prefix}_average`, null);
          setCalculation(`${prefix}_n_per_mm`, null);
        }
      });
      if (activeCount && completeCount === activeCount) assessment = outcomes.every(Boolean) ? 'PASS' : 'FAIL';
    }
    ctqHost.querySelectorAll('[data-ctq-assessment]').forEach(output => {
      output.textContent = assessment;
      output.dataset.result = assessment.toLowerCase();
    });
  }
  ctqHost?.addEventListener('input', updateCtqCalculations);
  ctqHost?.addEventListener('change', updateCtqCalculations);
  updateCtqCalculations();

  function collectRows() {
    if (ctqHost) return collectCtq();
    if (form.dataset.kind !== 'ipqc') return genericRows;
    const items = new Map();
    document.querySelectorAll('[data-item-id][data-observation-index]').forEach(input => {
      const id=input.dataset.itemId;
      if (!items.has(id)) items.set(id,{id,source_row:Number(input.dataset.sourceRow),observations:{}});
      const row=items.get(id); const index=input.dataset.observationIndex;
      row.observations[index] ||= {label:input.dataset.observationLabel,values:{}};
      row.observations[index].values[input.dataset.fieldLabel]=materialControlValue(input);
    });
    return [...items.values()];
  }
  function updateSummary() {
    const rows=collectRows();
    const host=document.querySelector('[data-review-summary]'); if(!host)return;
    let values;
    if (form.dataset.kind==='ipqc') {
      const fields=rows.flatMap(row=>Object.values(row.observations).flatMap(observation=>Object.values(observation.values)));
      const filled=fields.filter(value=>value).length;
      values=[['Total checks',rows.length],['Data fields',fields.length],['Completed',filled],['Remaining',fields.length-filled]];
    } else if (ctqHost) {
      const fields = [...ctqHost.querySelectorAll('[data-ctq-field]')];
      const completed = fields.filter(field => field.type === 'checkbox' ? field.checked : materialControlValue(field)).length;
      const assessment = ctqHost.querySelector('[data-ctq-assessment]')?.textContent || 'Pending';
      values=[['Controlled fields',fields.length],['Completed',completed],['Remaining',Math.max(0,fields.length-completed)],['Assessment',assessment]];
    } else {
      const results=rows.map(row=>row.Result); const filled=results.filter(value=>value && value!=='Not evaluated').length;
      values=[['Total checks',rows.length],['Evaluated',filled],['PASS',results.filter(x=>x==='PASS').length],['FAIL',results.filter(x=>x==='FAIL').length]];
    }
    host.replaceChildren(...values.map(([label,value])=>{const box=make('div');box.append(make('span',label),make('strong',String(value)));return box;}));
  }
  form.addEventListener('submit', event => {
    document.querySelector('#rows-json').value=JSON.stringify(collectRows());
    if (event.submitter?.value === 'submit') {
      const required=[...form.querySelectorAll('[required]')];
      const missing=required.find(field=>!field.value.trim());
      if (missing) { event.preventDefault(); show(0); missing.focus(); alert('Complete all basic information before submitting.'); return; }
    }
  });
  const confirm=document.querySelector('[data-confirm-submit]');
  const submit=document.querySelector('[data-submit]');
  confirm?.addEventListener('change',()=>submit.disabled=!confirm.checked);
})();

