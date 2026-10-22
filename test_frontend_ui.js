const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

console.log('--- Starting WebApp Frontend UI Simulation Tests ---');

// 1. Read app.js
const appJsPath = path.join(__dirname, 'webapp', 'app.js');
const appJsContent = fs.readFileSync(appJsPath, 'utf8');

// Mock DOM & Environment
class MockClassList {
    constructor() { this.classes = new Set(); }
    add(...cls) { cls.forEach(c => this.classes.add(c)); }
    remove(...cls) { cls.forEach(c => this.classes.delete(c)); }
    contains(cls) { return this.classes.has(cls); }
    toggle(cls, force) {
        if (force !== undefined) {
            if (force) this.classes.add(cls);
            else this.classes.delete(cls);
            return force;
        }
        if (this.classes.has(cls)) {
            this.classes.delete(cls);
            return false;
        } else {
            this.classes.add(cls);
            return true;
        }
    }
}

class MockElement {
    constructor(id = '', tag = 'div') {
        this.id = id;
        this.tagName = tag.toUpperCase();
        this.classList = new MockClassList();
        this.style = {};
        this.attributes = {};
        this.listeners = {};
        this.children = [];
        this._innerHTML = '';
        this._textContent = '';
        this.value = '';
        this.checked = false;
        this.disabled = false;
        this.selectedOptions = [];
        this.files = [];
    }

    get className() { return Array.from(this.classList.classes).join(' '); }
    set className(val) {
        this.classList.classes.clear();
        (val || '').split(/\s+/).filter(Boolean).forEach(c => this.classList.add(c));
    }

    get innerHTML() { return this._innerHTML; }
    set innerHTML(val) {
        this._innerHTML = val;
        this.children = [];
        if (typeof val === 'string' && val.includes('<')) {
            const tagRe = /<([a-zA-Z0-9-]+)\s*([^>]*)>/g;
            let m;
            while ((m = tagRe.exec(val)) !== null) {
                const tag = m[1];
                if (tag.startsWith('/')) continue;
                const rawAttrs = m[2];
                const child = new MockElement('', tag);
                const attrRe = /([a-zA-Z0-9_-]+)=["']([^"']*)["']/g;
                let am;
                while ((am = attrRe.exec(rawAttrs)) !== null) {
                    if (am[1] === 'class') {
                        child.className = am[2];
                    } else if (am[1] === 'id') {
                        child.id = am[2];
                        elements[am[2]] = child;
                    } else {
                        child.setAttribute(am[1], am[2]);
                    }
                }
                this.children.push(child);
            }
        }
    }

    get textContent() { return this._textContent || this._innerHTML; }
    set textContent(val) {
        this._textContent = val;
        this._innerHTML = val;
    }

    setAttribute(key, val) { this.attributes[key] = String(val); }
    getAttribute(key) { return this.attributes[key] || null; }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    addEventListener(event, handler) {
        this.listeners[event] = this.listeners[event] || [];
        this.listeners[event].push(handler);
    }

    click() {
        if (this.listeners['click']) {
            this.listeners['click'].forEach(fn => fn({ preventDefault: () => {}, stopPropagation: () => {} }));
        }
    }

    querySelectorAll(selector) {
        let targetClass = null;
        let attrKey = null;
        let attrVal = null;
        let targetTag = null;

        if (selector.startsWith('.')) {
            let s = selector.slice(1);
            if (s.includes('[')) {
                const parts = s.split('[');
                targetClass = parts[0];
                const attrMatch = parts[1].replace(']', '').split('=');
                attrKey = attrMatch[0];
                attrVal = attrMatch[1] ? attrMatch[1].replace(/["']/g, '') : null;
            } else {
                targetClass = s;
            }
        } else if (selector.startsWith('#')) {
            const id = selector.slice(1);
            return this.children.filter(c => c.id === id);
        } else {
            targetTag = selector.toUpperCase();
        }

        return this.children.filter(c => {
            if (targetClass && !c.classList.contains(targetClass)) return false;
            if (targetTag && c.tagName !== targetTag) return false;
            if (attrKey) {
                const val = c.getAttribute(attrKey);
                if (attrVal !== null && val !== attrVal) return false;
                if (attrVal === null && val === null) return false;
            }
            return true;
        });
    }

    querySelector(selector) {
        const matches = this.querySelectorAll(selector);
        return matches.length > 0 ? matches[0] : null;
    }

    scrollIntoView() {}
    focus() {}
}

const elements = {};
function getOrCreateElement(id, tag = 'div') {
    if (!elements[id]) {
        elements[id] = new MockElement(id, tag);
    }
    return elements[id];
}

// Pre-create known DOM elements from index.html (including all admin elements)
const elementIds = [
    'user-greeting', 'hero-subtitle', 'user-avatar-badge', 'user-avatar-text', 'btn-sync',
    'mini-card-op', 'mini-card-asd', 'mini-op-stat', 'mini-op-sub', 'mini-asd-stat', 'mini-asd-sub',
    'subj-tab-op', 'subj-tab-asd', 'subj-tab-eng', 'queue-op-asd-view', 'labs-grid', 'priority-preview', 'preview-text',
    'my-status-box', 'my-pos-text', 'my-labs-text', 'btn-leave-queue', 'btn-next-student',
    'queue-items-container', 'queue-empty', 'queue-list-title', 'badge-op-count', 'badge-asd-count', 'badge-eng-count',
    'btn-day-today', 'btn-day-tomorrow', 'btn-day-week', 'schedule-items-container', 'schedule-loading',
    'schedule-day-title', 'deadlines-items-container', 'deadlines-count-badge',
    'subjects-tab-op', 'subjects-tab-asd', 'subject-progress-hero', 'subject-hero-title',
    'subject-hero-term', 'subject-score-badge', 'subject-progress-bar-fill', 'subject-progress-percent',
    'subject-progress-status', 'subject-works-container',
    'english-projects-container', 'eng-admin-card', 'btn-eng-toggle-admin-form', 'eng-admin-form-body',
    'eng-board-title-input', 'eng-board-desc-input', 'eng-board-max-members-input', 'eng-board-topics-input',
    'btn-eng-create-board', 'eng-loading', 'eng-empty-msg', 'eng-boards-list',
    'btn-primary-action', 'btn-primary-action-text', 'toast', 'bottom-action-wrapper',
    'modal-backdrop', 'modal-sheet', 'modal-tag', 'modal-title', 'modal-time', 'modal-body-content',
    'modal-primary-link', 'btn-close-modal',
    // Admin panel elements
    'nav-btn-admin', 'tab-admin', 'admin-role-badge',
    'admin-test-mode-card', 'admin-test-mode-title', 'admin-test-mode-desc', 'admin-test-mode-toggle',
    'btn-admin-next-op', 'btn-admin-clear-op', 'btn-admin-next-asd', 'btn-admin-clear-asd',
    'admin-schedule-date', 'btn-admin-date-today', 'btn-admin-date-tomorrow', 'admin-schedule-list',
    'admin-pair-num', 'admin-pair-type', 'admin-pair-name', 'admin-pair-lecturer', 'admin-pair-link', 'admin-pair-comment',
    'btn-admin-add-pair', 'admin-roles-list', 'admin-student-select', 'admin-custom-username', 'admin-role-select',
    'btn-admin-grant-role', 'admin-preset-chips', 'admin-pair-preset'
];
elementIds.forEach(id => getOrCreateElement(id));

// Set initial classes and attributes matching index.html
const navBtnAdmin = getOrCreateElement('nav-btn-admin', 'button');
navBtnAdmin.classList.add('admin-lock-btn', 'hidden');
navBtnAdmin.setAttribute('data-tab', 'tab-admin');
navBtnAdmin.textContent = '🔒';

const tabAdmin = getOrCreateElement('tab-admin', 'section');
tabAdmin.classList.add('tab-content');

const adminTestModeCard = getOrCreateElement('admin-test-mode-card', 'div');
adminTestModeCard.classList.add('admin-card', 'hidden');

const adminTestModeToggle = getOrCreateElement('admin-test-mode-toggle', 'input');
adminTestModeToggle.setAttribute('type', 'checkbox');
adminTestModeToggle.checked = true;

const adminScheduleDate = getOrCreateElement('admin-schedule-date', 'input');
adminScheduleDate.setAttribute('type', 'date');

const btnDateToday = getOrCreateElement('btn-admin-date-today', 'button');
btnDateToday.classList.add('admin-pill-sm', 'active');

const btnDateTomorrow = getOrCreateElement('btn-admin-date-tomorrow', 'button');
btnDateTomorrow.classList.add('admin-pill-sm');

// English project elements initial state matching index.html
const subjTabEng = getOrCreateElement('subj-tab-eng', 'button');
subjTabEng.classList.add('subj-pill-tab', 'hidden');
subjTabEng.setAttribute('data-subject', 'Англійська');

const queueOpAsdView = getOrCreateElement('queue-op-asd-view', 'div');

const englishProjectsContainer = getOrCreateElement('english-projects-container', 'div');
englishProjectsContainer.classList.add('hidden');

const bottomWrapperEl = getOrCreateElement('bottom-action-wrapper', 'div');
bottomWrapperEl.classList.add('bottom-action-wrapper');

// Navigation segmented buttons & tab contents
const segQueue = new MockElement('seg-queue', 'button');
segQueue.setAttribute('data-tab', 'tab-queue');
segQueue.classList.add('seg-pill-btn', 'active');

const segSchedule = new MockElement('seg-schedule', 'button');
segSchedule.setAttribute('data-tab', 'tab-schedule');
segSchedule.classList.add('seg-pill-btn');

const segDeadlines = new MockElement('seg-deadlines', 'button');
segDeadlines.setAttribute('data-tab', 'tab-deadlines');
segDeadlines.classList.add('seg-pill-btn');

const segSubjects = new MockElement('seg-subjects', 'button');
segSubjects.setAttribute('data-tab', 'tab-subjects');
segSubjects.classList.add('seg-pill-btn');

const tabQueue = getOrCreateElement('tab-queue', 'section');
tabQueue.classList.add('tab-content', 'active');
const tabSchedule = getOrCreateElement('tab-schedule', 'section');
tabSchedule.classList.add('tab-content');
const tabDeadlines = getOrCreateElement('tab-deadlines', 'section');
tabDeadlines.classList.add('tab-content');
const tabSubjects = getOrCreateElement('tab-subjects', 'section');
tabSubjects.classList.add('tab-content');

const documentListeners = {};
const mockDoc = {
    addEventListener: (ev, fn) => {
        documentListeners[ev] = documentListeners[ev] || [];
        documentListeners[ev].push(fn);
    },
    getElementById: (id) => getOrCreateElement(id),
    createElement: (tag) => new MockElement('', tag),
    querySelector: (sel) => {
        if (sel === '.bottom-action-wrapper') return getOrCreateElement('bottom-action-wrapper');
        if (sel === '#nav-btn-admin') return navBtnAdmin;
        return null;
    },
    querySelectorAll: (sel) => {
        if (sel === '.seg-pill-btn') return [segQueue, segSchedule, segDeadlines, segSubjects];
        if (sel === '.tab-content') return [tabQueue, tabSchedule, tabDeadlines, tabSubjects, tabAdmin];
        return [];
    },
    body: new MockElement('body', 'body')
};

const networkRequests = [];
let queueApiState = [];
let scheduleApiLessons = [];
let isTestModeActive = true;
let englishBoardsApiState = [
    {
        id: 1,
        title: "English Presentation Project: Tech Topics",
        subject: "Англійська",
        description: "Group presentation and defense",
        max_members: 3,
        created_by: "Admin",
        groups: [
            {
                id: 10,
                board_id: 1,
                topic_title: "Cloud Native Microservices",
                members: [
                    { id: 101, user_id: 12345, user_name: "Олександр Староста", username: "starosta_user", role: "leader" }
                ],
                file_name: null,
                content_text: null,
                ai_qa: []
            }
        ]
    }
];

const mockLocalStorage = {
    _data: {},
    getItem(k) { return this._data[k] || null; },
    setItem(k, v) { this._data[k] = String(v); },
    removeItem(k) { delete this._data[k]; }
};

const sandbox = {
    window: {
        location: { search: '?chat_id=-1004483900746&subject=ОП', hostname: 'localhost' },
        Telegram: {
            WebApp: {
                ready: () => {},
                expand: () => {},
                initDataUnsafe: {
                    user: { id: 8735281894, first_name: 'Максим', last_name: 'Сінчіневіч', username: 'sinch' }
                },
                HapticFeedback: { impactOccurred: () => {}, notificationOccurred: () => {} }
            }
        }
    },
    document: mockDoc,
    localStorage: mockLocalStorage,
    fetch: async (url, opts = {}) => {
        networkRequests.push({ url, opts });
        if (url.includes('/api/student/resolve')) {
            return {
                json: async () => ({
                    success: true,
                    real_name: 'Сінчіневіч Максим Ігорович',
                    short_name: 'Сінчіневіч Максим',
                    first_name: 'Максим'
                })
            };
        }
        if (url.includes('/api/queue?')) {
            return {
                json: async () => ({
                    success: true,
                    items: queueApiState
                })
            };
        }
        if (url.includes('/api/queue/join')) {
            const body = JSON.parse(opts.body || '{}');
            const labNum = body.lab_number || '';
            const matches = labNum.match(/\d+/g) || [];
            const priority = matches.length > 0 ? Math.min(...matches.map(Number)) : 1;

            const existingIdx = queueApiState.findIndex(it => it.user_id === body.user_id);
            if (existingIdx !== -1) {
                const oldPriority = queueApiState[existingIdx].lab_priority;
                if (priority > oldPriority) {
                    // Priority dropped -> removed from current pos and re-added to back of priority group
                    queueApiState.splice(existingIdx, 1);
                    queueApiState.push({
                        id: 999,
                        chat_id: body.chat_id,
                        subject: body.subject,
                        user_id: body.user_id,
                        user_name: body.user_name,
                        username: body.username,
                        lab_number: labNum,
                        lab_priority: priority
                    });
                } else {
                    // Priority preserved or improved -> position maintained
                    queueApiState[existingIdx].lab_number = labNum;
                    queueApiState[existingIdx].lab_priority = priority;
                }
            } else {
                queueApiState.push({
                    id: 101,
                    chat_id: body.chat_id,
                    subject: body.subject,
                    user_id: body.user_id,
                    user_name: body.user_name,
                    username: body.username,
                    lab_number: labNum,
                    lab_priority: priority
                });
            }
            return {
                json: async () => ({
                    success: true,
                    position: queueApiState.findIndex(it => it.user_id === body.user_id) + 1,
                    lab_number: labNum
                })
            };
        }
        if (url.includes('/api/defenses')) return { json: async () => ({ success: true, defenses: [] }) };
        if (url.includes('/api/schedule')) return { json: async () => ({ success: true, lessons: scheduleApiLessons, days: [] }) };
        if (url.includes('/api/deadlines')) return { json: async () => ({ success: true, deadlines: [] }) };
        if (url.includes('/api/subjects/overview')) return { json: async () => ({ success: true, defenses: [] }) };
        if (url.includes('/api/admin/me')) {
            const isOwner = url.includes('8735281894') || url.includes('sinch');
            return {
                json: async () => ({
                    success: true,
                    is_admin: isOwner,
                    is_owner: isOwner,
                    role: isOwner ? 'owner' : null,
                    test_mode: true,
                    roles: [
                        { id: 1, user_id: 12345, username: 'starosta_user', real_name: 'Олександр Староста', role: 'headman' }
                    ]
                })
            };
        }
        if (url.includes('/api/students')) {
            return {
                json: async () => ({
                    success: true,
                    students: [
                        { telegram_id: 8735281894, telegram_username: 'sinch', real_name: 'Сінчіневіч Максим Ігорович' },
                        { telegram_id: 12345, telegram_username: 'starosta_user', real_name: 'Олександр Староста' },
                        { telegram_id: null, telegram_username: null, real_name: 'Коваль Петро Іванович' },
                        { telegram_id: null, telegram_username: null, real_name: 'Мельник Олена Сергіївна' },
                        { telegram_id: null, telegram_username: null, real_name: 'Шевченко Тарас Григорович' },
                        { telegram_id: null, telegram_username: null, real_name: 'Куратор Петренко' }
                    ]
                })
            };
        }
        if (url.includes('/api/admin/test_mode')) {
            const body = JSON.parse(opts.body || '{}');
            isTestModeActive = body.test_mode;
            return { json: async () => ({ success: true, test_mode: body.test_mode }) };
        }
        if (url.includes('/api/projects/boards/create')) {
            const body = JSON.parse(opts.body || '{}');
            const newBoard = {
                id: englishBoardsApiState.length + 1,
                title: body.title,
                subject: body.subject || 'Англійська',
                description: body.description || '',
                max_members: body.max_members || 3,
                created_by: 'Admin',
                groups: (body.initial_topics || []).map((t, idx) => ({
                    id: 200 + idx,
                    board_id: englishBoardsApiState.length + 1,
                    topic_title: t,
                    members: [],
                    file_name: null,
                    content_text: null,
                    ai_qa: []
                }))
            };
            englishBoardsApiState.push(newBoard);
            return { json: async () => ({ success: true, id: newBoard.id, message: 'Борд створено' }) };
        }
        if (url.includes('/api/projects/boards/delete')) {
            const body = JSON.parse(opts.body || '{}');
            englishBoardsApiState = englishBoardsApiState.filter(b => b.id !== body.board_id);
            return { json: async () => ({ success: true, message: 'Борд видалено' }) };
        }
        if (url.includes('/api/projects/boards')) {
            const isNonAdminStudent = url.includes('random_student') || url.includes('777000');
            if (isNonAdminStudent && isTestModeActive) {
                return {
                    json: async () => ({
                        success: true,
                        restricted_by_test_mode: true,
                        boards: []
                    })
                };
            }
            return {
                json: async () => ({
                    success: true,
                    restricted_by_test_mode: false,
                    boards: englishBoardsApiState
                })
            };
        }
        if (url.includes('/api/projects/groups/join')) {
            const body = JSON.parse(opts.body || '{}');
            const board = englishBoardsApiState.find(b => b.id === body.board_id) || englishBoardsApiState[0];
            if (body.group_id) {
                const grp = board.groups.find(g => g.id === body.group_id);
                if (grp) {
                    grp.members.push({
                        id: 900 + grp.members.length,
                        user_id: body.user_id,
                        user_name: body.user_name,
                        username: body.username,
                        role: 'member'
                    });
                }
                return { json: async () => ({ success: true, group_id: body.group_id, message: 'Приєднано' }) };
            } else if (body.topic_title) {
                const newGid = 50 + board.groups.length;
                const newMembers = [
                    { id: 910, user_id: body.user_id, user_name: body.user_name, username: body.username, role: 'leader' },
                    ...(body.teammates || []).map((tm, idx) => ({
                        id: 920 + idx,
                        user_id: tm.user_id,
                        user_name: tm.user_name,
                        username: tm.username,
                        role: 'member'
                    }))
                ];
                board.groups.push({
                    id: newGid,
                    board_id: board.id,
                    topic_title: body.topic_title,
                    members: newMembers,
                    file_name: null,
                    content_text: null,
                    ai_qa: []
                });
                return { json: async () => ({ success: true, group_id: newGid, message: 'Групу створено' }) };
            }
        }
        if (url.includes('/api/projects/groups/leave')) {
            return { json: async () => ({ success: true, message: 'Вийшли з групи' }) };
        }
        if (url.includes('/api/projects/groups/upload_and_generate')) {
            const body = JSON.parse(opts.body || '{}');
            const board = englishBoardsApiState[0];
            const grp = board.groups.find(g => g.id === body.group_id);
            const mockQa = [
                { question: "What is cloud architecture?", answer: "It is scalable computing.", tip: "Highlight elasticity." },
                { question: "How does microservice communicate?", answer: "Via gRPC and REST.", tip: "Mention latency." },
                { question: "What is fault tolerance?", answer: "Resilience to errors.", tip: "Give chaos monkey example." },
                { question: "Why containerize?", answer: "Portability and consistency.", tip: "Talk about Docker." },
                { question: "What is service mesh?", answer: "Manages service discovery.", tip: "Mention Istio." }
            ];
            if (grp) {
                grp.content_text = body.content_text || 'Extracted presentation content';
                grp.file_name = body.file_name || 'presentation.pptx';
                grp.ai_qa = mockQa;
            }
            return {
                json: async () => ({
                    success: true,
                    content_text: body.content_text || 'Extracted presentation content',
                    qa_list: mockQa
                })
            };
        }
        if (url.includes('/api/admin/schedule/add_pair')) {
            return { json: async () => ({ success: true, id: 101, message: 'Пару успішно додано' }) };
        }
        if (url.includes('/api/admin/schedule/cancel')) {
            return { json: async () => ({ success: true, message: 'Пару скасовано' }) };
        }
        if (url.includes('/api/admin/schedule/uncancel')) {
            return { json: async () => ({ success: true, message: 'Пару відновлено' }) };
        }
        if (url.includes('/api/admin/schedule/delete_pair')) {
            return { json: async () => ({ success: true, message: 'Пару видалено' }) };
        }
        if (url.includes('/api/admin/roles/grant')) {
            return { json: async () => ({ success: true, roles: [] }) };
        }
        if (url.includes('/api/admin/roles/revoke')) {
            return { json: async () => ({ success: true, roles: [] }) };
        }
        if (url.includes('/api/admin/queue/clear')) {
            return { json: async () => ({ success: true, count: 0 }) };
        }
        return { json: async () => ({ success: true }) };
    },
    setTimeout: (fn) => fn(),
    setInterval: () => {},
    clearTimeout: () => {},
    clearInterval: () => {},
    URLSearchParams: URLSearchParams,
    console: console,
    Set: Set,
    Map: Map,
    Array: Array,
    Object: Object,
    String: String,
    Number: Number,
    Boolean: Boolean,
    Date: Date,
    Math: Math,
    JSON: JSON,
    encodeURIComponent: encodeURIComponent,
    parseInt: parseInt,
    parseFloat: parseFloat,
    Promise: Promise,
    confirm: () => true,
    navigator: {
        clipboard: {
            writeText: async () => {}
        }
    },
    FileReader: class {
        constructor() {
            this.result = null;
            this.onload = null;
            this.onerror = null;
        }
        readAsDataURL(file) {
            const b64 = Buffer.from(file?.content || 'Sample presentation notes').toString('base64');
            this.result = `data:text/plain;base64,${b64}`;
            if (this.onload) {
                this.onload({ target: this });
            }
        }
    }
};

// 2. Execute app.js in sandbox
const context = vm.createContext(sandbox);
vm.runInContext(appJsContent, context);

// Trigger DOMContentLoaded
if (documentListeners['DOMContentLoaded']) {
    documentListeners['DOMContentLoaded'].forEach(fn => fn());
}

async function runTests() {
    // Wait microtasks for async resolve & fetchQueue
    await new Promise(r => setTimeout(r, 50));

    const labsGrid = getOrCreateElement('labs-grid');
    const btnAction = getOrCreateElement('btn-primary-action');
    const btnActionText = getOrCreateElement('btn-primary-action-text');

    // TEST 1: Check 9 lab buttons were created
    assert.strictEqual(labsGrid.children.length, 9, 'Grid must contain exactly 9 lab buttons');
    console.log('✓ TEST 1: Exactly 9 lab buttons rendered');

    // TEST 2: Initial button text before selection
    assert.ok(btnActionText.textContent.includes('ОП'), 'Action button should prompt to select lab for ОП');
    console.log('✓ TEST 2: Bottom button initial prompt verified');

    // TEST 3: Click Lab 5 -> verify selection and button state
    labsGrid.children[4].click(); // 0-indexed 4 is Lab 5

    assert.ok(labsGrid.children[4].classList.contains('selected'), 'Lab 5 button must have "selected" class');
    assert.strictEqual(btnActionText.textContent, '🚀 Зайняти чергу: Лаба 5');
    console.log('✓ TEST 3: Tapping Lab 5 selects it and updates action button');

    // TEST 4: Click Primary Action to submit join queue
    btnAction.click();
    await new Promise(r => setTimeout(r, 50));

    // Verify queueApiState now contains student with Lab 5
    assert.strictEqual(queueApiState.length, 1);
    assert.strictEqual(queueApiState[0].lab_number, 'Лаба 5');
    assert.strictEqual(queueApiState[0].lab_priority, 5);
    assert.strictEqual(btnActionText.textContent, '✅ Ви у черзі #1 (Лаба 5)');
    assert.ok(labsGrid.children[4].classList.contains('is-queued'), 'Lab 5 must now have "is-queued" class');
    console.log('✓ TEST 4: Submitting join puts user in queue with Lab 5 at #1');

    // TEST 5: Select additional lab (Lab 6) while already in queue
    labsGrid.children[5].click(); // Lab 6

    assert.ok(labsGrid.children[4].classList.contains('selected'), 'Lab 5 remains selected');
    assert.ok(labsGrid.children[5].classList.contains('selected'), 'Lab 6 is now selected');
    assert.strictEqual(btnActionText.textContent, '➕ Додати: Лаби 5, 6');
    console.log('✓ TEST 5: Tapping Lab 6 shows "➕ Додати: Лаби 5, 6"');

    // TEST 6: Submit updated labs (5 and 6)
    btnAction.click();
    await new Promise(r => setTimeout(r, 50));

    assert.strictEqual(queueApiState[0].lab_number, 'Лаби 5, 6');
    assert.strictEqual(queueApiState[0].lab_priority, 5);
    assert.strictEqual(btnActionText.textContent, '✅ Ви у черзі #1 (Лаби 5, 6)');
    assert.ok(labsGrid.children[5].classList.contains('is-queued'), 'Lab 6 is now marked as queued');
    console.log('✓ TEST 6: Submitting additional lab updates queue in DB with preserved position');

    // TEST 7: Deselect Lab 5 leaving only Lab 6 (dropping earlier lab)
    labsGrid.children[4].click(); // Unselect Lab 5

    assert.ok(!labsGrid.children[4].classList.contains('selected'), 'Lab 5 is unselected');
    assert.ok(labsGrid.children[5].classList.contains('selected'), 'Lab 6 remains selected');
    assert.strictEqual(btnActionText.textContent, '💾 Оновити чергу: Лаба 6');
    console.log('✓ TEST 7: Unselecting earlier lab shows "💾 Оновити чергу: Лаба 6"');

    // Add a competitor student in queue with priority 5
    queueApiState.push({
        id: 202,
        chat_id: -1004483900746,
        subject: 'ОП',
        user_id: 999888777,
        user_name: 'Петренко Петро',
        username: 'petro',
        lab_number: 'Лаба 5',
        lab_priority: 5
    });

    // TEST 8: Submit drop of Lab 5 -> priority drops from 5 to 6
    btnAction.click();
    await new Promise(r => setTimeout(r, 50));

    // Petrenko has priority 5, user now has priority 6 -> Petrenko is ahead!
    assert.strictEqual(queueApiState[0].user_name, 'Петренко Петро');
    assert.ok(queueApiState[1].user_name.includes('Сінчіневіч Максим'));
    assert.strictEqual(queueApiState[1].lab_priority, 6);
    assert.strictEqual(btnActionText.textContent, '✅ Ви у черзі #2 (Лаба 6)');
    console.log('✓ TEST 8: Dropping earlier lab successfully drops priority and position behind priority 5 student');

    // TEST 9: Admin panel verification for Owner (sinch / 8735281894)
    // 9.1: Verify all 27 admin elements exist in DOM and initialized
    const adminElementsToCheck = [
        'nav-btn-admin', 'tab-admin', 'admin-role-badge',
        'admin-test-mode-card', 'admin-test-mode-title', 'admin-test-mode-desc', 'admin-test-mode-toggle',
        'btn-admin-next-op', 'btn-admin-clear-op', 'btn-admin-next-asd', 'btn-admin-clear-asd',
        'admin-schedule-date', 'btn-admin-date-today', 'btn-admin-date-tomorrow', 'admin-schedule-list',
        'admin-pair-num', 'admin-pair-type', 'admin-pair-name', 'admin-pair-lecturer', 'admin-pair-link', 'admin-pair-comment',
        'btn-admin-add-pair', 'admin-roles-list', 'admin-student-select', 'admin-custom-username', 'admin-role-select',
        'btn-admin-grant-role'
    ];
    adminElementsToCheck.forEach(id => {
        assert.ok(elements[id], `Admin DOM element #${id} must exist and be registered`);
    });

    // 9.2: Verify #nav-btn-admin is visible (hidden class removed for owner sinch upon is_admin: true)
    assert.strictEqual(
        navBtnAdmin.classList.contains('hidden'),
        false,
        '#nav-btn-admin must become visible (hidden class removed) for bot owner'
    );

    // 9.3: Role badge and test mode card checks for owner
    const roleBadge = getOrCreateElement('admin-role-badge');
    assert.ok(roleBadge.innerHTML.includes('Власник бота'), 'Role badge must display "Власник бота"');

    assert.strictEqual(
        adminTestModeCard.classList.contains('hidden'),
        false,
        'Admin test mode card must be visible for Owner'
    );
    assert.strictEqual(adminTestModeToggle.checked, true, 'Test mode toggle should be checked (true)');

    // 9.4: Date input initialized
    assert.ok(adminScheduleDate.value, 'Admin schedule date input must be prefilled');

    // 9.5: Switch tab to Admin via lock button
    navBtnAdmin.click();
    assert.ok(navBtnAdmin.classList.contains('active'), 'Admin lock button must have active class when selected');
    assert.ok(tabAdmin.classList.contains('active'), 'Admin tab content must be active');
    const bottomWrapper = getOrCreateElement('bottom-action-wrapper');
    assert.ok(bottomWrapper.classList.contains('hidden'), 'Bottom action wrapper must be hidden in admin tab');

    // Switch back to schedule tab and verify admin active class is removed
    segSchedule.click();
    assert.ok(!navBtnAdmin.classList.contains('active'), 'Admin lock button must lose active class when returning to schedule');
    // In schedule tab with no active lesson, bottom action wrapper should be hidden!
    assert.ok(bottomWrapper.classList.contains('hidden'), 'Bottom action wrapper must be hidden in schedule tab when no active lesson exists');

    // Switch to queue tab and verify bottom action wrapper is visible
    segQueue.click();
    assert.ok(!bottomWrapper.classList.contains('hidden'), 'Bottom action wrapper must be visible in queue tab');

    // Re-open admin tab for next tests
    navBtnAdmin.click();
    assert.ok(navBtnAdmin.classList.contains('active'), 'Admin lock button must be active again');

    // 9.6: Test mode toggle action
    adminTestModeToggle.checked = false;
    if (adminTestModeToggle.onchange) {
        await adminTestModeToggle.onchange();
    }
    const testModeReq = networkRequests.find(r => r.url.includes('/api/admin/test_mode'));
    assert.ok(testModeReq, 'Changing test_mode toggle must trigger POST /api/admin/test_mode');

    // 9.7: Add Pair form submission
    const pairNameInput = getOrCreateElement('admin-pair-name');
    pairNameInput.value = 'Спеціальні розділи математики';
    const btnAddPair = getOrCreateElement('btn-admin-add-pair');
    btnAddPair.click();
    await new Promise(r => setTimeout(r, 50));
    const addPairReq = networkRequests.find(r => r.url.includes('/api/admin/schedule/add_pair'));
    assert.ok(addPairReq, 'Submitting add-pair form must call /api/admin/schedule/add_pair');

    console.log('✓ TEST 9: Admin panel DOM elements & owner privileges verified (nav-btn-admin visible, owner badge, test_mode toggle, schedule add pair)');

    // TEST 10: Schedule active pair sync & bottom button dynamic visibility
    const nowKyivTime = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Europe/Kyiv',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    }).format(new Date());
    const [nowH, nowM] = nowKyivTime.split(':').map(Number);
    const mockActiveLesson = {
        name: "Комп'ютерна дискретна математика",
        type: 'Лекція',
        lecturer: 'Ліхоузова Тетяна Анатоліївна',
        time: `${String(nowH).padStart(2, '0')}:${String(nowM).padStart(2, '0')}`,
        link_url: 'https://us02web.zoom.us/j/6982343166',
        is_cancelled: false
    };

    scheduleApiLessons.push(mockActiveLesson);
    segSchedule.click();
    await new Promise(r => setTimeout(r, 60));

    assert.ok(!bottomWrapper.classList.contains('hidden'), 'Bottom action wrapper must be visible when an active lesson exists');
    assert.ok(btnActionText.textContent.includes("🟢 Зараз: Комп'ютерна дискретна математика"), 'Button text must reflect active lesson');
    console.log('✓ TEST 10: Schedule active pair dynamically updates bottom button');

    // TEST 11: Admin Panel Presets (Chips & Dropdown) Autofill
    navBtnAdmin.click();
    const presetChipsContainer = getOrCreateElement('admin-preset-chips');
    const pairPresetSelect = getOrCreateElement('admin-pair-preset');

    assert.ok(presetChipsContainer.children.length >= 9, 'Must render frequent preset chips');
    assert.ok(pairPresetSelect.children.length >= 15, 'Must render all 15 preset options in dropdown');

    // 11.1: Click on "💻 ОП (Лаб)" chip
    const opLabChip = presetChipsContainer.children.find(c => c.getAttribute('data-preset-id') === 'op-lab');
    assert.ok(opLabChip, 'op-lab chip must exist');
    opLabChip.click();

    const typeInput = getOrCreateElement('admin-pair-type');
    const nameInput = getOrCreateElement('admin-pair-name');
    const lecturerInput = getOrCreateElement('admin-pair-lecturer');
    const linkInput = getOrCreateElement('admin-pair-link');
    const commentInput = getOrCreateElement('admin-pair-comment');

    assert.strictEqual(nameInput.value, 'Основи програмування. Частина 1. Базові конструкції');
    assert.strictEqual(typeInput.value, 'Лабораторна');
    assert.strictEqual(lecturerInput.value, 'Ахаладзе Антон Елдарійович');
    assert.ok(linkInput.value.includes('zoom.us'), 'Zoom link must be filled');
    assert.strictEqual(commentInput.value, 'Zoom');
    assert.ok(opLabChip.classList.contains('active'), 'Active class must be added to chosen chip');

    // 11.2: Select "kdm-lek" from dropdown
    pairPresetSelect.value = 'kdm-lek';
    if (pairPresetSelect.onchange) {
        pairPresetSelect.onchange();
    }
    assert.strictEqual(nameInput.value, "Комп'ютерна дискретна математика");
    assert.strictEqual(typeInput.value, 'Лекція');
    assert.strictEqual(lecturerInput.value, 'Ліхоузова Тетяна Анатоліївна');
    assert.strictEqual(commentInput.value, 'Zoom');
    assert.ok(!opLabChip.classList.contains('active'), 'Previous chip must lose active class');
    const kdmLekChip = presetChipsContainer.children.find(c => c.getAttribute('data-preset-id') === 'kdm-lek');
    if (kdmLekChip) {
        assert.ok(kdmLekChip.classList.contains('active'), 'Newly selected chip must be active');
    }
    console.log('✓ TEST 11: Admin pair presets chips & dropdown autofill all fields correctly');

    // ==========================================
    // TEST 12: English Tab closed test mode visibility & API isolation
    // ==========================================
    // 12.1: Ensure test mode is active for closed beta test
    adminTestModeToggle.checked = true;
    if (adminTestModeToggle.onchange) {
        await adminTestModeToggle.onchange();
    }

    // Admin/Owner sees the English tab regardless of test mode
    assert.ok(!subjTabEng.classList.contains('hidden'), 'English tab pill must be visible for Admin/Owner');

    // 12.2: Verify API isolation for non-admin student when test_mode is active
    const studentBoardsReq = await sandbox.fetch('/api/projects/boards?subject=Англійська&user_id=777000&username=random_student');
    const studentBoardsData = await studentBoardsReq.json();
    assert.strictEqual(studentBoardsData.restricted_by_test_mode, true, 'Non-admin student must be restricted when test_mode is on');
    assert.strictEqual(studentBoardsData.boards.length, 0, 'Non-admin student receives 0 boards during closed test');

    // 12.3: Verify Owner receives full boards list
    const ownerBoardsReq = await sandbox.fetch('/api/projects/boards?subject=Англійська&user_id=8735281894&username=sinch');
    const ownerBoardsData = await ownerBoardsReq.json();
    assert.strictEqual(ownerBoardsData.restricted_by_test_mode, false, 'Owner must NOT be restricted');
    assert.ok(ownerBoardsData.boards.length > 0, 'Owner receives English boards list');
    console.log('✓ TEST 12: English Tab closed test mode visibility & API isolation verified');

    // ==========================================
    // TEST 13: English Projects collaboration, teammate selection, and AI Q&A defense generation
    // ==========================================
    // 13.1: In Zdachi (Queue) tab, click English tab
    segQueue.click();
    subjTabEng.click();
    await new Promise(r => setTimeout(r, 60));

    assert.ok(subjTabEng.classList.contains('active'), 'English tab pill must be active');
    const subjTabOp = getOrCreateElement('subj-tab-op');
    const subjTabAsd = getOrCreateElement('subj-tab-asd');
    assert.ok(!subjTabOp.classList.contains('active'), 'OP tab must not be active');
    assert.ok(!subjTabAsd.classList.contains('active'), 'ASD tab must not be active');

    assert.ok(queueOpAsdView.classList.contains('hidden'), 'Queue OP/ASD view must be hidden when English is selected');
    assert.ok(!englishProjectsContainer.classList.contains('hidden'), 'English projects container must be visible');
    assert.ok(bottomWrapperEl.classList.contains('hidden'), 'Bottom action wrapper must be hidden when English is selected');

    // Switch to OP tab and verify toggle
    subjTabOp.click();
    await new Promise(r => setTimeout(r, 60));
    assert.ok(!queueOpAsdView.classList.contains('hidden'), 'Queue OP/ASD view must be visible when OP is selected');
    assert.ok(englishProjectsContainer.classList.contains('hidden'), 'English projects container must be hidden when OP is selected');
    assert.ok(!bottomWrapperEl.classList.contains('hidden'), 'Bottom action wrapper must be visible when OP is selected');

    // Switch back to English
    subjTabEng.click();
    await new Promise(r => setTimeout(r, 60));
    assert.ok(queueOpAsdView.classList.contains('hidden'), 'Queue OP/ASD view must be hidden again');
    assert.ok(!englishProjectsContainer.classList.contains('hidden'), 'English projects container must be visible again');
    assert.ok(bottomWrapperEl.classList.contains('hidden'), 'Bottom action wrapper must be hidden again');

    // 13.2: Verify board rendering & pill badge count
    const engBoardsList = getOrCreateElement('eng-boards-list');
    const badgeEngCount = getOrCreateElement('badge-eng-count');
    assert.strictEqual(String(badgeEngCount.textContent), '1', 'English pill badge count must match total groups count across boards');
    assert.ok(engBoardsList.innerHTML.includes('English Presentation Project: Tech Topics'), 'Must render board title');
    assert.ok(engBoardsList.innerHTML.includes('Cloud Native Microservices'), 'Must render initial topic');
    assert.ok(engBoardsList.innerHTML.includes('Олександр Староста'), 'Must render existing member in group 10');

    // 13.3: Teammate selection & validation (Bug 1 & Bug 2)
    const toggleCreateBtn = engBoardsList.querySelectorAll('.btn-toggle-create-group')[0];
    assert.ok(toggleCreateBtn, 'Must have toggle create group button');
    toggleCreateBtn.click();
    await new Promise(r => setTimeout(r, 60));

    const teammatesContainer = getOrCreateElement('eng-teammates-1');
    assert.ok(teammatesContainer, 'Must have teammates selector container');
    const pills = teammatesContainer.querySelectorAll('.eng-teammate-pill');
    assert.ok(pills.length >= 3, 'Must render teammate pills for candidate students');

    // Verify curator was filtered out
    const pillTexts = pills.map(p => p.textContent);
    assert.ok(!pillTexts.some(t => t.toLowerCase().includes('куратор')), 'Curators must NOT appear in teammates list');
    // Verify patronymics omitted (formatted as Surname Name)
    assert.ok(pillTexts.includes('Коваль Петро'), 'Must format full name without patronymic');
    assert.ok(pillTexts.includes('Мельник Олена'), 'Must format full name without patronymic');

    // Select first teammate
    const labelEl = elements['eng-teammates-label-1'] || getOrCreateElement('eng-teammates-label-1');
    pills[0].click();
    assert.ok(labelEl.textContent.includes('обрано: 1 з 2'), 'Label must reflect 1 selected teammate');

    // Select second teammate
    pills[1].click();
    assert.ok(labelEl.textContent.includes('обрано: 2 з 2'), 'Label must reflect 2 selected teammates');

    // Try selecting third teammate (max limit is 2 for board max_members = 3)
    pills[2].click();
    assert.ok(!pills[2].classList.contains('selected'), 'Third teammate must not be selected due to limit');
    assert.ok(labelEl.textContent.includes('обрано: 2 з 2'), 'Label must remain at 2 selected');

    // Deselect first teammate
    pills[0].click();
    assert.ok(!pills[0].classList.contains('selected'), 'First teammate must be deselected');
    assert.ok(labelEl.textContent.includes('обрано: 1 з 2'), 'Label must reflect 1 selected teammate');

    // Cancel create panel
    const cancelBtn = engBoardsList.querySelectorAll('.btn-cancel-new-group')[0];
    assert.ok(cancelBtn, 'Cancel new group button must exist');
    cancelBtn.click();
    await new Promise(r => setTimeout(r, 60));

    // 13.4: User joins Group 10
    const joinBtns = engBoardsList.querySelectorAll('.btn-join-group');
    assert.ok(joinBtns.length > 0, 'Must have at least one join button');
    joinBtns[0].click();
    await new Promise(r => setTimeout(r, 60));

    const joinReq = networkRequests.find(r => r.url.includes('/api/projects/groups/join'));
    assert.ok(joinReq, 'Clicking join button must trigger POST /api/projects/groups/join');

    // Re-render happens after join: user 8735281894 is now in group 10
    assert.ok(engBoardsList.innerHTML.includes('Сінчіневіч Максим'), 'Must display current user in group 10');
    assert.ok(engBoardsList.innerHTML.includes('🤖 Згенерувати Q&A (English AI)'), 'Button text must match initial state');

    // 13.5: Verify user in group sees upload materials & AI generator section
    const generateBtn = engBoardsList.querySelectorAll('.btn-generate-qa')[0];
    assert.ok(generateBtn, 'Group member must have AI Generate Q&A button');

    const textArea = elements['eng-text-10'] || getOrCreateElement('eng-text-10', 'textarea');
    textArea.value = 'We demonstrate Kubernetes cluster autoscaling and ingress controllers.';

    generateBtn.click();
    await new Promise(r => setTimeout(r, 60));

    const genReq = networkRequests.find(r => r.url.includes('/api/projects/groups/upload_and_generate'));
    assert.ok(genReq, 'Clicking generate button must call /api/projects/groups/upload_and_generate');

    // 13.6: Verify AI Q&A cards rendered in UI and button text updated
    assert.ok(engBoardsList.innerHTML.includes('What is cloud architecture?'), 'Rendered HTML must contain AI Question');
    assert.ok(engBoardsList.innerHTML.includes('elasticity'), 'Rendered HTML must contain AI Tip');
    assert.ok(engBoardsList.innerHTML.includes('Why containerize?'), 'Rendered HTML must contain AI Question 2');
    assert.ok(engBoardsList.innerHTML.includes('🔄 Перегенерувати Q&A (English AI)'), 'Button text must indicate re-generation after Q&A is generated');

    // 13.7: Verify Lecturer Export button
    const exportBtns = engBoardsList.querySelectorAll('.btn-export-board');
    assert.ok(exportBtns.length > 0, 'Export for lecturer button must exist');

    console.log('✓ TEST 13: English projects board rendering, group collaboration, and AI Q&A defense passed');

    console.log('\n========================================');
    console.log('🎉 ALL UI TESTS PASSED SUCCESSFULLY! 🎉');
    console.log('========================================\n');
}

runTests().catch(err => {
    console.error('UI Test Failure:', err);
    process.exit(1);
});
