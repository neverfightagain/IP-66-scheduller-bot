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
    }

    get textContent() { return this._textContent; }
    set textContent(val) { this._textContent = val; }

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
        return this.children.filter(c => {
            if (selector.startsWith('.')) {
                return c.classList.contains(selector.slice(1));
            }
            return true;
        });
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
    'subj-tab-op', 'subj-tab-asd', 'labs-grid', 'priority-preview', 'preview-text',
    'my-status-box', 'my-pos-text', 'my-labs-text', 'btn-leave-queue', 'btn-next-student',
    'queue-items-container', 'queue-empty', 'queue-list-title', 'badge-op-count', 'badge-asd-count',
    'btn-day-today', 'btn-day-tomorrow', 'btn-day-week', 'schedule-items-container', 'schedule-loading',
    'schedule-day-title', 'deadlines-items-container', 'deadlines-count-badge',
    'subjects-tab-op', 'subjects-tab-asd', 'subject-progress-hero', 'subject-hero-title',
    'subject-hero-term', 'subject-score-badge', 'subject-progress-bar-fill', 'subject-progress-percent',
    'subject-progress-status', 'subject-works-container',
    'btn-primary-action', 'btn-primary-action-text', 'toast',
    'modal-backdrop', 'modal-sheet', 'modal-tag', 'modal-title', 'modal-time', 'modal-body-content',
    'modal-primary-link', 'btn-close-modal',
    // Admin panel elements
    'nav-btn-admin', 'tab-admin', 'admin-role-badge',
    'admin-test-mode-card', 'admin-test-mode-title', 'admin-test-mode-desc', 'admin-test-mode-toggle',
    'btn-admin-next-op', 'btn-admin-clear-op', 'btn-admin-next-asd', 'btn-admin-clear-asd',
    'admin-schedule-date', 'btn-admin-date-today', 'btn-admin-date-tomorrow', 'admin-schedule-list',
    'admin-pair-num', 'admin-pair-type', 'admin-pair-name', 'admin-pair-lecturer', 'admin-pair-link', 'admin-pair-comment',
    'btn-admin-add-pair', 'admin-roles-list', 'admin-student-select', 'admin-custom-username', 'admin-role-select',
    'btn-admin-grant-role'
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
        if (url.includes('/api/schedule')) return { json: async () => ({ success: true, lessons: [], days: [] }) };
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
                        { telegram_id: 12345, telegram_username: 'starosta_user', real_name: 'Олександр Староста' }
                    ]
                })
            };
        }
        if (url.includes('/api/admin/test_mode')) {
            const body = JSON.parse(opts.body || '{}');
            return { json: async () => ({ success: true, test_mode: body.test_mode }) };
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
    confirm: () => true
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

    // Switch back to schedule tab and verify admin active class is removed and bottom wrapper is restored
    segSchedule.click();
    assert.ok(!navBtnAdmin.classList.contains('active'), 'Admin lock button must lose active class when returning to schedule');
    assert.ok(!bottomWrapper.classList.contains('hidden'), 'Bottom action wrapper must be unhidden when returning to schedule');

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

    console.log('\n========================================');
    console.log('🎉 ALL UI TESTS PASSED SUCCESSFULLY! 🎉');
    console.log('========================================\n');
}

runTests().catch(err => {
    console.error('UI Test Failure:', err);
    process.exit(1);
});
