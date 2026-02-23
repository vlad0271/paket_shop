import { fetchOptions, fetchStandardSizes } from './api.js';

let options = {};
let standardSizes = {}; // { 'S': {width, length, height}, ... }

export async function initConstructor() {
    try {
        const [allOptions, sizes] = await Promise.all([fetchOptions(), fetchStandardSizes()]);
        groupOptions(allOptions);
        populateSelects();
        injectStandardSizeRadios(sizes);
        setupModal();
    } catch (error) {
        console.error('Ошибка инициализации конструктора:', error);
    }
}

function injectStandardSizeRadios(sizes) {
    const radioGroup = document.querySelector('#bottles-choice .radio-group');
    const customLabel = radioGroup.querySelector('label:last-child');

    sizes.forEach(s => {
        const label = `${s.width}×${s.length}×${s.height} мм`;
        bottleLabels[s.key] = `Стандартный пакет ${label}`;
        standardSizes[s.key] = { width: s.width, length: s.length, height: s.height };

        const el = document.createElement('label');
        el.innerHTML = `<input type="radio" name="bottles" value="${s.key}"> Стандартный ${label}`;
        radioGroup.insertBefore(el, customLabel);
    });
}

function groupOptions(allOptions) {
    options = { paper: [], color: [], handle: [] };
    allOptions.forEach(opt => {
        if (options[opt.category]) options[opt.category].push(opt);
    });
}

function populateSelects() {
    const paperSelect  = document.getElementById('paper-type');
    const colorSelect  = document.getElementById('color');
    const handleSelect = document.getElementById('handle-type');

    options.paper.forEach(opt => {
        const o = document.createElement('option');
        o.value = opt.value; o.textContent = opt.name;
        paperSelect.appendChild(o);
    });
    options.color.forEach(opt => {
        const o = document.createElement('option');
        o.value = opt.value; o.textContent = opt.name;
        colorSelect.appendChild(o);
    });
    options.handle.forEach(opt => {
        const o = document.createElement('option');
        o.value = opt.value; o.textContent = opt.name;
        handleSelect.appendChild(o);
    });
}

const bottleLabels = {
    '1': 'Пакет для 1 бутылки',
    '2': 'Пакет для 2 бутылок',
    '3': 'Пакет для 3 бутылок',
    'custom': 'Произвольный размер',
    'unknown': 'Размеров не знаю',
};

function openModal(modal, bottles) {
    const bottlesChoice = document.getElementById('bottles-choice');
    const bottlesFixed  = document.getElementById('bottles-fixed');
    const modalTitle    = document.getElementById('modal-title');

    if (bottles) {
        const radio = document.querySelector(`input[name="bottles"][value="${bottles}"]`);
        if (radio) radio.checked = true;
        bottlesChoice.style.display = 'none';
        bottlesFixed.style.display  = 'block';
        document.getElementById('bottles-fixed-text').textContent = bottleLabels[bottles];
        modalTitle.textContent = bottleLabels[bottles];
    } else {
        bottlesChoice.style.display = 'block';
        bottlesFixed.style.display  = 'none';
        modalTitle.textContent = 'Конструктор пакета';
    }

    modal.style.display = 'block';
    updatePreview();
}

// ─── Геометрия пакета ─────────────────────────────────────

const BAG_COLORS = {
    brown:  { fill: '#c49a3c', stroke: '#a07828', fold: 'rgba(0,0,0,0.13)' },
    white:  { fill: '#ede8df', stroke: '#ccc5bb', fold: 'rgba(0,0,0,0.09)' },
    black:  { fill: '#383838', stroke: '#555',    fold: 'rgba(255,255,255,0.1)' },
    orange: { fill: '#e87722', stroke: '#c45e00', fold: 'rgba(0,0,0,0.12)' },
};

const PAPER_DEFAULT_COLOR = { kraft: 'brown', coated: 'white' };

// Силуэты бутылок (только для режима бутылок, позиции относительно дефолтной геометрии)
const BOTTLE_SHAPES = {
    '1': `<rect x="88" y="118" width="24" height="90" rx="5" fill="rgba(0,0,0,0.1)"/>`,
    '2': `<rect x="70" y="118" width="22" height="90" rx="4" fill="rgba(0,0,0,0.1)"/>
          <rect x="108" y="118" width="22" height="90" rx="4" fill="rgba(0,0,0,0.1)"/>`,
    '3': `<rect x="56"  y="120" width="20" height="88" rx="4" fill="rgba(0,0,0,0.08)"/>
          <rect x="90"  y="116" width="20" height="92" rx="4" fill="rgba(0,0,0,0.11)"/>
          <rect x="124" y="120" width="20" height="88" rx="4" fill="rgba(0,0,0,0.08)"/>`,
};

function getBagDimensions() {
    const choice = document.querySelector('input[name="bottles"]:checked')?.value;
    if (choice === 'custom') {
        const w = parseInt(document.getElementById('custom-width')?.value)  || 0;
        const l = parseInt(document.getElementById('custom-length')?.value) || 0;
        const h = parseInt(document.getElementById('custom-height')?.value) || 0;
        if (w > 0 && l > 0 && h > 0) return { width: w, length: l, height: h };
        return null;
    }
    return standardSizes[choice] || null;
}

// Вычисляет SVG-координаты пакета на основе реальных размеров
function computeBagGeo(dims) {
    if (!dims) {
        // Дефолтная геометрия для режима бутылок
        return { x: 20, y: 80, w: 160, h: 220, foldH: 30, leftFold: 52, rightFold: 148 };
    }
    const MAX_W = 156, MAX_H = 218;
    const scale = Math.min(MAX_W / dims.width, MAX_H / dims.height);
    const w = Math.round(dims.width  * scale);
    const h = Math.round(dims.height * scale);
    const x = Math.round((200 - w) / 2);
    const y = 80;
    const foldH  = Math.max(18, Math.round(h * 0.12));
    // Боковые линии сгиба — пропорциональны глубине дна (length)
    const gusset = Math.min(Math.round(dims.length * scale * 0.45), Math.round(w * 0.28));
    return { x, y, w, h, foldH, leftFold: x + gusset, rightFold: x + w - gusset };
}

function ropeHandles(strokeColor, geo) {
    const lc = geo.x + geo.w * 0.28;
    const rc = geo.x + geo.w * 0.72;
    const hw = Math.max(10, geo.w * 0.12);
    const arcTop = 22;
    return `
        <path d="M${lc - hw},${geo.y} C${lc - hw},${arcTop} ${lc + hw},${arcTop} ${lc + hw},${geo.y}"
              stroke="${strokeColor}" fill="none" stroke-width="9" stroke-linecap="round"/>
        <path d="M${rc - hw},${geo.y} C${rc - hw},${arcTop} ${rc + hw},${arcTop} ${rc + hw},${geo.y}"
              stroke="${strokeColor}" fill="none" stroke-width="9" stroke-linecap="round"/>`;
}

function ribbonHandles(geo) {
    const c  = '#c89090';
    const lc = geo.x + geo.w * 0.32;
    const rc = geo.x + geo.w * 0.68;
    const hw = Math.max(8, geo.w * 0.09);
    const arcTop = 28;
    const mid = (lc + rc) / 2;
    return `
        <path d="M${lc - hw},${geo.y} C${lc - hw},${arcTop + 16} ${lc + hw * 0.6},${arcTop} ${lc + hw},${geo.y}"
              stroke="${c}" fill="none" stroke-width="4.5" stroke-linecap="round"/>
        <path d="M${rc + hw},${geo.y} C${rc + hw},${arcTop + 16} ${rc - hw * 0.6},${arcTop} ${rc - hw},${geo.y}"
              stroke="${c}" fill="none" stroke-width="4.5" stroke-linecap="round"/>
        <line x1="${lc + hw}" y1="${arcTop}" x2="${rc - hw}" y2="${arcTop}"
              stroke="${c}" stroke-width="4.5" stroke-linecap="round"/>
        <circle cx="${mid}" cy="${arcTop}" r="6" fill="${c}"/>`;
}

function updatePreview() {
    const bottleEl  = document.querySelector('input[name="bottles"]:checked');
    const bottles   = bottleEl ? bottleEl.value : '2';
    const color      = document.getElementById('color')?.value      || '';
    const handleType = document.getElementById('handle-type')?.value || '';
    const paperType  = document.getElementById('paper-type')?.value  || '';
    const hasPrint   = document.getElementById('has-print')?.checked || false;

    const bodyEl = document.getElementById('preview-body');
    if (!bodyEl) return;

    const palette = BAG_COLORS[color] || BAG_COLORS.brown;
    const dims    = getBagDimensions();
    const geo     = computeBagGeo(dims);

    // Тело пакета
    bodyEl.setAttribute('x',      geo.x);
    bodyEl.setAttribute('y',      geo.y);
    bodyEl.setAttribute('width',  geo.w);
    bodyEl.setAttribute('height', geo.h);
    bodyEl.setAttribute('fill',   palette.fill);
    bodyEl.setAttribute('stroke', palette.stroke);

    // Верхний отворот
    const foldEl = document.getElementById('preview-fold');
    foldEl.setAttribute('x',      geo.x);
    foldEl.setAttribute('y',      geo.y);
    foldEl.setAttribute('width',  geo.w);
    foldEl.setAttribute('height', geo.foldH);
    foldEl.setAttribute('fill',   palette.fold);

    // Боковые линии сгиба
    document.getElementById('preview-folds').innerHTML = `
        <line x1="${geo.leftFold}"  y1="${geo.y + 2}" x2="${geo.leftFold}"  y2="${geo.y + geo.h - 2}" stroke="rgba(0,0,0,0.1)" stroke-width="1.5"/>
        <line x1="${geo.rightFold}" y1="${geo.y + 2}" x2="${geo.rightFold}" y2="${geo.y + geo.h - 2}" stroke="rgba(0,0,0,0.1)" stroke-width="1.5"/>`;

    // Ручки
    const handleStroke = color === 'black' ? '#777' : '#7a5418';
    document.getElementById('preview-handles').innerHTML =
        handleType === 'ribbon' ? ribbonHandles(geo) : ropeHandles(handleStroke, geo);

    // Бутылки (только в режиме бутылок с дефолтной геометрией)
    document.getElementById('preview-bottle-shapes').innerHTML =
        dims ? '' : (BOTTLE_SHAPES[bottles] || BOTTLE_SHAPES['2']);

    // Блеск для премиум-бумаги
    const premiumEl = document.getElementById('preview-premium');
    premiumEl.setAttribute('x',      geo.x);
    premiumEl.setAttribute('y',      geo.y);
    premiumEl.setAttribute('width',  geo.w);
    premiumEl.setAttribute('height', geo.h);
    premiumEl.style.display = paperType === 'premium' ? '' : 'none';

    // Печать логотипа
    const printEl = document.getElementById('preview-print');
    const cx = geo.x + geo.w / 2;
    const cy = geo.y + geo.foldH + (geo.h - geo.foldH) / 2;
    printEl.querySelector('circle').setAttribute('cx', cx);
    printEl.querySelector('circle').setAttribute('cy', cy);
    printEl.querySelectorAll('text')[0].setAttribute('x', cx);
    printEl.querySelectorAll('text')[0].setAttribute('y', cy - 6);
    printEl.querySelectorAll('text')[1].setAttribute('x', cx);
    printEl.querySelectorAll('text')[1].setAttribute('y', cy + 7);
    printEl.style.display = hasPrint ? '' : 'none';
}

function toggleCustomFields(choice) {
    const isUnknown = choice === 'unknown';

    document.getElementById('custom-size-fields').style.display =
        choice === 'custom' ? 'block' : 'none';
    ['custom-width', 'custom-length', 'custom-height'].forEach(id => {
        document.getElementById(id).required = choice === 'custom';
    });

    document.getElementById('package-options').style.display = isUnknown ? 'none' : '';
    document.getElementById('order-form-section').style.display = isUnknown ? 'block' : 'none';
}

function setupPreview() {
    document.querySelectorAll('input[name="bottles"]').forEach(r => {
        r.addEventListener('change', () => {
            updatePreview();
            toggleCustomFields(r.value);
        });
    });
    document.getElementById('color')?.addEventListener('change',       updatePreview);
    document.getElementById('handle-type')?.addEventListener('change', updatePreview);
    document.getElementById('paper-type')?.addEventListener('change', (e) => {
        const defaultColor = PAPER_DEFAULT_COLOR[e.target.value];
        if (defaultColor) document.getElementById('color').value = defaultColor;
        updatePreview();
    });
    document.getElementById('has-print')?.addEventListener('change',   updatePreview);
    ['custom-width', 'custom-length', 'custom-height'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', updatePreview);
    });
}

function setupModal() {
    const modal    = document.getElementById('constructor-modal');
    const closeBtn = modal.querySelector('.close');

    const makeOrderBtn = document.getElementById('make-order-btn');
    if (makeOrderBtn) {
        makeOrderBtn.addEventListener('click', () => openModal(modal, null));
    }

    document.querySelectorAll('.order-bottle-btn').forEach(btn => {
        btn.addEventListener('click', () => openModal(modal, btn.dataset.bottles));
    });

    setupPreview();

    closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    window.addEventListener('click', (e) => {
        if (e.target === modal) modal.style.display = 'none';
    });
}

export function getFormData() {
    const form     = document.getElementById('constructor-form');
    const formData = new FormData(form);
    const choice     = formData.get('bottles');
    const isStandard = !!standardSizes[choice];
    const isCustom   = choice === 'custom';
    const isUnknown  = choice === 'unknown';
    return {
        bottles:       (isStandard || isCustom || isUnknown) ? 0 : parseInt(choice),
        bag_size:      isStandard ? choice : (isUnknown ? 'unknown' : null),
        custom_width:  isCustom ? parseInt(formData.get('custom_width'))  : null,
        custom_length: isCustom ? parseInt(formData.get('custom_length')) : null,
        custom_height: isCustom ? parseInt(formData.get('custom_height')) : null,
        paper_type:    isUnknown ? '' : formData.get('paper_type'),
        color:         isUnknown ? '' : formData.get('color'),
        handle_type:   isUnknown ? '' : formData.get('handle_type'),
        has_print:     isUnknown ? false : formData.get('has_print') === 'on',
        quantity:      isUnknown ? 1 : parseInt(formData.get('quantity'))
    };
}
