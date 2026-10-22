// --- Telegram Mini App Frontend Controller (ІП-66 Портал) ---
document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
        tg.ready();
        tg.expand();
    }

    const PATRONYMIC_SUFFIXES = ['вич', 'вна', 'івич', 'івна', 'ович', 'овна', 'євич', 'ївна', 'євна'];

    function parsePersonName(fullName) {
        if (!fullName) return { surname: '', name: '', patronymic: '' };
        const parts = fullName.trim().split(/\s+/);
        if (!parts.length) return { surname: '', name: '', patronymic: '' };

        if (parts[0].toLowerCase() === 'куратор') {
            return { surname: 'Куратор', name: parts.slice(1).join(' '), patronymic: '' };
        }
        if (parts.length === 1) {
            return { surname: '', name: parts[0], patronymic: '' };
        }
        if (parts.length >= 3) {
            const p1Lower = parts[1].toLowerCase();
            const p2Lower = parts[2].toLowerCase();
            const p1IsPatronymic = PATRONYMIC_SUFFIXES.some(s => p1Lower.endsWith(s));
            const p2IsPatronymic = PATRONYMIC_SUFFIXES.some(s => p2Lower.endsWith(s));
            if (p1IsPatronymic && !p2IsPatronymic) {
                return { surname: parts[0], name: parts[2], patronymic: parts[1] };
            }
            return { surname: parts[0], name: parts[1], patronymic: parts[2] };
        }
        return { surname: parts[0], name: parts[1], patronymic: '' };
    }

    function formatQueueName(fullName) {
        if (!fullName) return '';
        const { surname, name } = parsePersonName(fullName);
        if (surname === 'Куратор') return `Куратор ${name}`;
        if (surname && name) return `${surname} ${name}`;
        return name || surname || fullName.trim();
    }

    function extractFirstName(fullName) {
        if (!fullName) return 'Студент';
        const { surname, name } = parsePersonName(fullName);
        return name || surname || fullName.trim() || 'Студент';
    }

    function formatLocation(loc) {
        if (!loc) return 'Онлайн';
        if (typeof loc === 'object') {
            return loc.title || loc.name || 'Онлайн';
        }
        const s = String(loc).trim();
        return s || 'Онлайн';
    }

    // Параметри URL від бота (chat_id, subject)
    const urlParams = new URLSearchParams(window.location.search);
    const chatId = parseInt(urlParams.get('chat_id')) || 0;
    const initialSubject = (urlParams.get('subject') || 'ОП').toUpperCase();

    // Інформація про користувача з Telegram WebApp SDK
    const tgUser = tg?.initDataUnsafe?.user;

    // Перевірка середовища запуску: якщо відкрито у звичайному браузері без Telegram WebApp
    const BOT_USERNAME = 'kpi_shedule_ip_66_bot';
    const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    const isDebug = urlParams.get('debug') === '1' || urlParams.get('test') === '1';

    if ((!tgUser || !tgUser.id) && !isLocalhost && !isDebug) {
        const safeChat = chatId ? String(chatId).replace('-', 'm') : '0';
        const subjCode = initialSubject ? `_${initialSubject.toLowerCase()}` : '';
        const botUrl = `https://t.me/${BOT_USERNAME}?start=app_${safeChat}${subjCode}`;

        document.body.innerHTML = `
            <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:100vh; padding:24px; text-align:center; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #fdfbf7; color: #1e293b;">
                <div style="width: 76px; height: 76px; border-radius: 22px; background: linear-gradient(135deg, #6366f1, #4f46e5); display: flex; align-items: center; justify-content: center; font-size: 38px; color: #fff; margin-bottom: 20px; box-shadow: 0 10px 25px rgba(79, 70, 229, 0.35);">
                    🤖
                </div>
                <h2 style="margin: 0 0 10px 0; font-size: 22px; font-weight: 700; color: #0f172a;">Відкриття через Telegram</h2>
                <p style="margin: 0 0 24px 0; font-size: 15px; color: #64748b; max-width: 340px; line-height: 1.5;">
                    У звичайному браузері неможливо ідентифікувати ваш студентський акаунт. Відкрийте додаток через Telegram-бота для синхронізації черг та профілю.
                </p>
                <a href="${botUrl}" style="display:inline-flex; align-items:center; justify-content:center; gap: 8px; background: #4f46e5; color: #ffffff; padding: 14px 28px; border-radius: 14px; text-decoration: none; font-weight: 600; font-size: 16px; box-shadow: 0 6px 20px rgba(79, 70, 229, 0.3); transition: transform 0.15s ease;">
                    <span>🚀</span> Відкрити в Telegram
                </a>
                <p style="margin-top: 18px; font-size: 13px; color: #94a3b8;">Автоматичне перенаправлення...</p>
            </div>
        `;
        setTimeout(() => {
            window.location.href = botUrl;
        }, 300);
        return;
    }

    const initialRawName = tgUser ? [tgUser.first_name, tgUser.last_name].filter(Boolean).join(' ') : 'Студент';
    const initialFirstName = tgUser?.first_name ? extractFirstName(tgUser.first_name) : 'Студент';
    const currentUser = {
        id: tgUser?.id || 999001,
        name: formatQueueName(initialRawName) || 'Студент',
        firstName: initialFirstName,
        username: tgUser?.username || 'student',
        photoUrl: tgUser?.photo_url || ''
    };

    // Миттєве відновлення кешованої ідентичності студента з localStorage
    try {
        const cachedIdKey = 'ip66_student_identity_' + (currentUser.id || 'me');
        const cachedId = localStorage.getItem(cachedIdKey);
        if (cachedId) {
            const parsed = JSON.parse(cachedId);
            if (parsed.realName) currentUser.realName = parsed.realName;
            if (parsed.name) currentUser.name = parsed.name;
            if (parsed.firstName) currentUser.firstName = parsed.firstName;
        }
    } catch (_) {}

    // Стан додатку
    let activeSubject = ['ОП', 'АСД'].includes(initialSubject) ? initialSubject : 'ОП';
    let selectedLabs = new Set();
    let currentQueue = [];
    let allQueuesData = { 'ОП': [], 'АСД': [] };
    let scheduleLessons = [];
    let deadlinesCache = [];
    let scheduleDay = 'today';
    let currentTab = 'tab-queue';
    let pollInterval = null;
    let userHasManuallyEditedLabs = { 'ОП': false, 'АСД': false };

    // Збереження виконаних дедлайнів у localStorage окремо для кожного студента
    function getCompletedDeadlinesKey() {
        return currentUser?.id ? `ip66_completed_deadlines_${currentUser.id}` : 'ip66_completed_deadlines';
    }

    function loadCompletedDeadlines() {
        try {
            const raw = localStorage.getItem(getCompletedDeadlinesKey());
            if (!raw) return new Set();
            const arr = JSON.parse(raw);
            return new Set(Array.isArray(arr) ? arr : []);
        } catch (e) {
            return new Set();
        }
    }

    function saveCompletedDeadlines(set) {
        try {
            const arr = Array.from(set);
            localStorage.setItem(getCompletedDeadlinesKey(), JSON.stringify(arr));
        } catch (e) {
            console.error('Failed to save completed deadlines to localStorage', e);
        }
    }

    // DOM Elements
    const userGreetingEl = document.getElementById('user-greeting');
    const heroSubtitleEl = document.getElementById('hero-subtitle');
    const userAvatarBadge = document.getElementById('user-avatar-badge');
    const userAvatarText = document.getElementById('user-avatar-text');
    const btnSync = document.getElementById('btn-sync');

    // Mini Cards (ОП / АСД)
    const miniCardOp = document.getElementById('mini-card-op');
    const miniCardAsd = document.getElementById('mini-card-asd');
    const miniOpStat = document.getElementById('mini-op-stat');
    const miniOpSub = document.getElementById('mini-op-sub');
    const miniAsdStat = document.getElementById('mini-asd-stat');
    const miniAsdSub = document.getElementById('mini-asd-sub');

    // Tabs
    const segButtons = document.querySelectorAll('.seg-pill-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    // Queue Elements
    const subjTabOp = document.getElementById('subj-tab-op');
    const subjTabAsd = document.getElementById('subj-tab-asd');
    const labsGridEl = document.getElementById('labs-grid');
    const priorityPreviewEl = document.getElementById('priority-preview');
    const previewTextEl = document.getElementById('preview-text');
    const myStatusBox = document.getElementById('my-status-box');
    const myPosText = document.getElementById('my-pos-text');
    const myLabsText = document.getElementById('my-labs-text');
    const btnLeaveQueue = document.getElementById('btn-leave-queue');
    const btnNextStudent = document.getElementById('btn-next-student');
    const queueItemsContainer = document.getElementById('queue-items-container');
    const queueEmptyEl = document.getElementById('queue-empty');
    const queueListTitle = document.getElementById('queue-list-title');
    const badgeOpCount = document.getElementById('badge-op-count');
    const badgeAsdCount = document.getElementById('badge-asd-count');

    // Schedule Elements
    const btnDayToday = document.getElementById('btn-day-today');
    const btnDayTomorrow = document.getElementById('btn-day-tomorrow');
    const btnDayWeek = document.getElementById('btn-day-week');
    const scheduleItemsContainer = document.getElementById('schedule-items-container');
    const scheduleLoading = document.getElementById('schedule-loading');
    const scheduleDayTitle = document.getElementById('schedule-day-title');

    // Deadlines Elements
    const deadlinesItemsContainer = document.getElementById('deadlines-items-container');
    const deadlinesCountBadge = document.getElementById('deadlines-count-badge');

    // Subjects Elements (ОП Практикуми / АСД Практичні роботи)
    const subjectsTabOp = document.getElementById('subjects-tab-op');
    const subjectsTabAsd = document.getElementById('subjects-tab-asd');
    const subjectProgressHero = document.getElementById('subject-progress-hero');
    const subjectHeroTitle = document.getElementById('subject-hero-title');
    const subjectHeroTerm = document.getElementById('subject-hero-term');
    const subjectScoreBadge = document.getElementById('subject-score-badge');
    const subjectProgressBarFill = document.getElementById('subject-progress-bar-fill');
    const subjectProgressPercent = document.getElementById('subject-progress-percent');
    const subjectProgressStatus = document.getElementById('subject-progress-status');
    const subjectWorksContainer = document.getElementById('subject-works-container');

    let activeSubjectsSubj = 'ОП';
    let officialAiDefenses = [];

    // Bottom Action Button & Toast
    const btnPrimaryAction = document.getElementById('btn-primary-action');
    const btnPrimaryActionText = document.getElementById('btn-primary-action-text');
    const toastEl = document.getElementById('toast');

    // Modal Elements
    const modalBackdrop = document.getElementById('modal-backdrop');
    const modalTag = document.getElementById('modal-tag');
    const modalTitle = document.getElementById('modal-title');
    const modalTime = document.getElementById('modal-time');
    const modalBodyContent = document.getElementById('modal-body-content');
    const modalPrimaryLink = document.getElementById('modal-primary-link');
    const btnCloseModal = document.getElementById('btn-close-modal');

    // Toast Helper
    function showToast(text, duration = 2500) {
        if (!toastEl) return;
        toastEl.textContent = text;
        toastEl.classList.remove('hidden');
        setTimeout(() => {
            toastEl.classList.add('hidden');
        }, duration);
    }

    // Modal Sheet Functions
    let isClosingModal = false;

    function openModal({ tag, title, time, body, linkUrl, linkText }) {
        if (!modalBackdrop) return;
        const modalSheet = document.getElementById('modal-sheet');
        if (modalSheet) modalSheet.classList.remove('closing');
        modalBackdrop.classList.remove('closing');
        isClosingModal = false;

        if (modalTag) modalTag.textContent = tag || 'Деталі';
        if (modalTitle) modalTitle.textContent = title || '';
        if (modalTime) modalTime.textContent = time || '';
        if (modalBodyContent) modalBodyContent.innerHTML = body || '';

        if (modalPrimaryLink) {
            if (linkUrl && linkUrl !== '#') {
                modalPrimaryLink.href = linkUrl;
                modalPrimaryLink.textContent = linkText || '🚀 Відкрити посилання';
                modalPrimaryLink.style.display = 'flex';
                modalPrimaryLink.onclick = (e) => {
                    if (tg?.openLink) {
                        e.preventDefault();
                        tg.openLink(linkUrl);
                    }
                };
            } else {
                modalPrimaryLink.style.display = 'none';
                modalPrimaryLink.onclick = null;
            }
        }

        modalBackdrop.classList.remove('hidden');
    }

    function closeModal() {
        if (!modalBackdrop || modalBackdrop.classList.contains('hidden') || isClosingModal) return;
        const modalSheet = document.getElementById('modal-sheet');
        if (!modalSheet) {
            modalBackdrop.classList.add('hidden');
            return;
        }

        isClosingModal = true;
        modalSheet.classList.add('closing');
        modalBackdrop.classList.add('closing');

        setTimeout(() => {
            modalBackdrop.classList.add('hidden');
            modalSheet.classList.remove('closing');
            modalBackdrop.classList.remove('closing');
            isClosingModal = false;
        }, 220);
    }

    if (btnCloseModal) btnCloseModal.addEventListener('click', closeModal);
    if (modalBackdrop) {
        modalBackdrop.addEventListener('click', (e) => {
            if (e.target === modalBackdrop) closeModal();
        });
    }

    // 1. Ініціалізація заголовку та неклікабельної аватарки
    if (userGreetingEl) {
        userGreetingEl.textContent = `Привіт, ${currentUser.firstName}! ✨`;
    }

    if (userAvatarBadge) {
        if (currentUser.photoUrl) {
            userAvatarBadge.style.backgroundImage = `url(${currentUser.photoUrl})`;
            userAvatarBadge.style.backgroundSize = 'cover';
            if (userAvatarText) userAvatarText.textContent = '';
        } else {
            if (userAvatarText) userAvatarText.textContent = currentUser.firstName.charAt(0).toUpperCase();
        }
    }

    // Розпізнавання реального імені користувача з реєстру групи
    async function resolveStudentIdentity() {
        try {
            const res = await fetch(`/api/student/resolve?user_id=${currentUser.id}&username=${encodeURIComponent(currentUser.username || '')}`);
            const data = await res.json();
            if (data.success && data.real_name) {
                currentUser.realName = data.real_name;
                currentUser.name = data.short_name || formatQueueName(data.real_name);
                const firstName = data.first_name || extractFirstName(data.real_name);
                currentUser.firstName = firstName;
                try {
                    const cachedIdKey = 'ip66_student_identity_' + (currentUser.id || 'me');
                    localStorage.setItem(cachedIdKey, JSON.stringify({
                        realName: currentUser.realName,
                        name: currentUser.name,
                        firstName: currentUser.firstName
                    }));
                } catch (_) {}
                if (userGreetingEl) {
                    userGreetingEl.textContent = `Привіт, ${firstName}! ✨`;
                }
                if (userAvatarText && !currentUser.photoUrl) {
                    userAvatarText.textContent = firstName.charAt(0).toUpperCase();
                }
                fetchStudentDefenses();
                fetchQueue();
                updateBottomButtonState();
            }
        } catch (e) {
            // Резервний варіант: залишаємо Telegram-ім'я
        }
    }
    resolveStudentIdentity();

    // Явна кнопка оновлення
    if (btnSync) {
        btnSync.addEventListener('click', async () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
            showToast("🔄 Оновлюю дані...");
            await refreshAllData();
            showToast("✅ Дані оновлено!");
        });
    }

    // 2. Інтерактивні міні-картки ОП та АСД
    if (miniCardOp) {
        miniCardOp.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            switchQueueSubject('ОП');
            switchToTab('tab-queue');
        });
    }

    if (miniCardAsd) {
        miniCardAsd.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            switchQueueSubject('АСД');
            switchToTab('tab-queue');
        });
    }

    function openLessonModal(lesson) {
        const link = lesson.link_url || '';
        openModal({
            tag: `Пара ${lesson.pair_number || 1} (${lesson.time || '10:15'})`,
            title: lesson.name,
            time: `${lesson.type || 'Пара'} • ${formatLocation(lesson.location)}`,
            body: `
                <div style="margin-bottom:8px;"><b>👤 Викладач:</b> ${escapeHtml(lesson.lecturer || 'Не вказано')}</div>
                ${lesson.link_comment ? `<div style="font-size:12.5px; color:#6D28D9; background:#F3E8FF; padding:8px 12px; border-radius:12px; margin-bottom:8px;">📝 ${escapeHtml(lesson.link_comment)}</div>` : ''}
                ${!link ? '<div style="color:var(--text-secondary); font-size:13px;">ℹ️ Посилання на онлайн-заняття ще не збережено старостою.</div>' : ''}
            `,
            linkUrl: link,
            linkText: '🚀 Приєднатися (Zoom / Teams)'
        });
    }

    // 3. Перемикання вкладок
    function switchToTab(targetTab) {
        currentTab = targetTab;
        segButtons.forEach(b => {
            if (b.getAttribute('data-tab') === targetTab) {
                b.classList.add('active');
            } else {
                b.classList.remove('active');
            }
        });

        const navBtnAdmin = document.getElementById('nav-btn-admin');
        if (navBtnAdmin) {
            if (targetTab === 'tab-admin') {
                navBtnAdmin.classList.add('active');
                navBtnAdmin.textContent = '🔓';
            } else {
                navBtnAdmin.classList.remove('active');
                navBtnAdmin.textContent = '🔒';
            }
        }

        tabContents.forEach(c => {
            if (c.id === targetTab) {
                c.classList.add('active');
            } else {
                c.classList.remove('active');
            }
        });

        // Ховаємо нижню плаваючу кнопку, коли відкрита адмінка, щоб не перекривати інпути
        const bottomWrapper = (typeof document.querySelector === 'function' ? document.querySelector('.bottom-action-wrapper') : null) || btnPrimaryAction?.parentElement;
        if (bottomWrapper) {
            if (targetTab === 'tab-admin') {
                bottomWrapper.classList.add('hidden');
            } else {
                bottomWrapper.classList.remove('hidden');
            }
        }

        updateBottomButtonState();
    }

    segButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            switchToTab(targetTab);
            if (targetTab === 'tab-schedule') fetchSchedule(scheduleDay);
            if (targetTab === 'tab-deadlines') fetchDeadlines();
            if (targetTab === 'tab-queue') fetchQueue();
            if (targetTab === 'tab-subjects') fetchSubjectsOverview();
        });
    });

    const navBtnAdminEl = document.getElementById('nav-btn-admin');
    if (navBtnAdminEl) {
        navBtnAdminEl.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            if (currentTab === 'tab-admin') {
                switchToTab('tab-queue');
                fetchQueue();
            } else {
                switchToTab('tab-admin');
                if (typeof loadAdminScheduleDate === 'function') {
                    const adminDateEl = document.getElementById('admin-schedule-date');
                    loadAdminScheduleDate(adminDateEl ? adminDateEl.value : getKyivDateString(0));
                }
            }
        });
    }

    function formatShortLabsLabel(sortedArray) {
        if (!sortedArray || sortedArray.length === 0) return '';
        if (sortedArray.length === 1) return `Лаба ${sortedArray[0]}`;
        if (sortedArray.length <= 3) return `Лаби ${sortedArray.join(', ')}`;
        return `${sortedArray.length} робіт`;
    }

    // 4. Оновлення нижньої кнопки дії
    function updateBottomButtonState() {
        if (!btnPrimaryAction || !btnPrimaryActionText) return;

        if (currentTab === 'tab-queue') {
            const myItem = currentQueue.find(item => isMeItem(item));
            if (myItem) {
                const myIdx = currentQueue.indexOf(myItem) + 1;
                const currentLabNums = new Set(((myItem.lab_number || '').match(/\d+/g) || []).map(Number));
                const isSame = (selectedLabs.size === currentLabNums.size) &&
                               Array.from(selectedLabs).every(n => currentLabNums.has(n));

                if (isSame) {
                    if (currentLabNums.size <= 3) {
                        btnPrimaryActionText.textContent = `✅ Ви у черзі #${myIdx} (${myItem.lab_number || 'Лаба ' + (myItem.lab_priority || 1)})`;
                    } else {
                        btnPrimaryActionText.textContent = `✅ Ви у черзі #${myIdx} (${currentLabNums.size} робіт)`;
                    }
                    btnPrimaryAction.classList.remove('btn-action-update');
                } else {
                    const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
                    if (sorted.length === 0) {
                        btnPrimaryActionText.textContent = `⚠️ Оберіть хоча б одну роботу`;
                        btnPrimaryAction.classList.remove('btn-action-update');
                    } else {
                        const shortLabel = formatShortLabsLabel(sorted);
                        const oldNums = Array.from(currentLabNums);
                        const oldMin = oldNums.length > 0 ? Math.min(...oldNums) : 999;
                        const newMin = sorted[0];
                        const isAdded = sorted.some(n => !currentLabNums.has(n));

                        if (sorted.length <= 3) {
                            if (isAdded && newMin <= oldMin) {
                                btnPrimaryActionText.textContent = `➕ Додати: ${shortLabel}`;
                            } else {
                                btnPrimaryActionText.textContent = `💾 Оновити чергу: ${shortLabel}`;
                            }
                        } else {
                            if (isAdded && newMin <= oldMin) {
                                btnPrimaryActionText.textContent = `➕ Зберегти у черзі (${sorted.length} робіт)`;
                            } else {
                                btnPrimaryActionText.textContent = `💾 Оновити чергу (${sorted.length} робіт)`;
                            }
                        }
                        btnPrimaryAction.classList.add('btn-action-update');
                    }
                }
            } else {
                btnPrimaryAction.classList.remove('btn-action-update');
                const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
                if (sorted.length === 0) {
                    btnPrimaryActionText.textContent = `✋ Зайняти чергу ${activeSubject} (оберіть лабу)`;
                } else {
                    const shortLabel = formatShortLabsLabel(sorted);
                    if (sorted.length <= 3) {
                        btnPrimaryActionText.textContent = `🚀 Зайняти чергу: ${shortLabel}`;
                    } else {
                        btnPrimaryActionText.textContent = `🚀 Зайняти чергу (${sorted.length} робіт)`;
                    }
                    btnPrimaryAction.classList.add('btn-action-update');
                }
            }
            btnPrimaryAction.disabled = false;
        } else if (currentTab === 'tab-schedule') {
            const firstWithLink = scheduleLessons.find(l => l.link_url);
            if (firstWithLink) {
                btnPrimaryActionText.textContent = `🔗 Приєднатися: ${firstWithLink.name.substring(0, 22)}...`;
            } else {
                btnPrimaryActionText.textContent = `📅 Розклад пар ІП-66`;
            }
            btnPrimaryAction.disabled = false;
        } else if (currentTab === 'tab-deadlines') {
            btnPrimaryActionText.textContent = `🔄 Оновити дедлайни`;
            btnPrimaryAction.disabled = false;
        } else if (currentTab === 'tab-subjects') {
            btnPrimaryActionText.textContent = `🔄 Оновити прогрес`;
            btnPrimaryAction.disabled = false;
        } else if (currentTab === 'tab-admin') {
            btnPrimaryActionText.textContent = `⚙️ Панель старостату`;
            btnPrimaryAction.disabled = false;
            btnPrimaryAction.classList.remove('btn-action-update');
        }
    }

    // Обробник кліку на головну кнопку
    if (btnPrimaryAction) {
        btnPrimaryAction.addEventListener('click', async () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');

            if (currentTab === 'tab-queue') {
                const myItem = currentQueue.find(item => isMeItem(item));
                if (myItem) {
                    const currentLabNums = new Set(((myItem.lab_number || '').match(/\d+/g) || []).map(Number));
                    const isSame = (selectedLabs.size === currentLabNums.size) &&
                                   Array.from(selectedLabs).every(n => currentLabNums.has(n));
                    if (isSame) {
                        showToast(`Ви вже у черзі ${activeSubject} на позиції #${currentQueue.indexOf(myItem) + 1}!\nЩоб додати ще роботу, оберіть її у сітці вище 👆`, 3500);
                        if (labsGridEl) {
                            labsGridEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            labsGridEl.classList.add('attention-pulse');
                            setTimeout(() => labsGridEl.classList.remove('attention-pulse'), 500);
                        }
                        return;
                    }
                }

                const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
                if (sorted.length === 0) {
                    if (myItem) {
                        showToast("⚠️ Оберіть хоча б одну роботу або натисніть «Вийти»", 3000);
                    } else {
                        toggleLab(1);
                        showToast("🎯 Обрано Лабу 1. Натисніть ще раз, щоб підтвердити, або оберіть іншу!", 3000);
                    }
                    if (labsGridEl) labsGridEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    return;
                }
                await submitJoinQueue();
            } else if (currentTab === 'tab-schedule') {
                const firstWithLink = scheduleLessons.find(l => l.link_url);
                if (firstWithLink) {
                    openLessonModal(firstWithLink);
                } else {
                    showToast("У розкладі немає збережених Zoom/Meet посилань");
                }
            } else if (currentTab === 'tab-deadlines') {
                await fetchDeadlines();
                showToast("Дедлайни оновлено!");
            } else if (currentTab === 'tab-subjects') {
                await fetchSubjectsOverview();
                showToast(`Дані з ${activeSubjectsSubj} оновлено! 📚`);
            }
        });
    }

    let studentDefenses = [];

    async function fetchStudentDefenses() {
        if (!currentUser?.id) return;
        try {
            const res = await fetch(`/api/defenses?user_id=${currentUser.id}&subject=${encodeURIComponent(activeSubject)}`);
            const data = await res.json();
            if (data.success && Array.isArray(data.defenses)) {
                studentDefenses = data.defenses;
                renderLabsGrid();
            }
        } catch (_) {}
    }

    // 5. Логіка черги: вибір лаб 1..9
    function renderLabsGrid() {
        if (!labsGridEl) return;
        labsGridEl.innerHTML = '';

        const defendedLabNumbers = new Set();
        (studentDefenses || []).forEach(d => {
            const numMatch = (d.lab_number || '').match(/\d+/);
            if (numMatch) defendedLabNumbers.add(parseInt(numMatch[0]));
        });

        // Також додаємо відмітки з локального збереження студента
        const myName = currentUser?.name || 'Студент';
        const localSet = loadStudentLocalProgress(myName, activeSubject);
        if (localSet) {
            localSet.forEach(n => defendedLabNumbers.add(n));
        }

        // Роботи, на які студент ВЖЕ стоїть у черзі зараз
        const myItem = currentQueue.find(item => isMeItem(item));
        const myQueuedLabNums = new Set();
        if (myItem && myItem.lab_number) {
            const matches = myItem.lab_number.match(/\d+/g);
            if (matches) {
                matches.forEach(n => myQueuedLabNums.add(parseInt(n, 10)));
            }
        }

        for (let i = 1; i <= 9; i++) {
            const btn = document.createElement('button');
            const isQueued = myQueuedLabNums.has(i);
            const isSelected = selectedLabs.has(i);
            const isDefended = defendedLabNumbers.has(i);

            let icon = '▫️';
            if (isSelected) {
                icon = isQueued ? '⏳' : '✅';
            } else if (isDefended) {
                icon = '✓';
            } else if (isQueued) {
                icon = '▫️';
            }

            const classes = ['lab-pill-btn'];
            if (isQueued) classes.push('is-queued');
            if (isSelected) classes.push('selected');
            if (isDefended) classes.push('is-defended');

            btn.className = classes.join(' ');
            btn.innerHTML = `
                <span class="lab-btn-icon">${icon}</span>
                <span class="lab-btn-text">Лаба ${i}</span>
            `;
            btn.setAttribute('type', 'button');
            btn.addEventListener('click', () => {
                toggleLab(i);
            });
            labsGridEl.appendChild(btn);
        }
    }

    function toggleLab(num) {
        userHasManuallyEditedLabs[activeSubject] = true;
        if (selectedLabs.has(num)) {
            selectedLabs.delete(num);
        } else {
            selectedLabs.add(num);
        }
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
        renderLabsGrid();
        updatePriorityPreview();
        updateBottomButtonState();
    }

    function updatePriorityPreview() {
        const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
        if (sorted.length === 0) {
            if (priorityPreviewEl) priorityPreviewEl.classList.add('hidden');
            return;
        }

        const minLab = sorted[0];
        const labsText = sorted.length === 1 ? `Лаба ${minLab}` : `Лаби ${sorted.join(', ')}`;
        const myItem = currentQueue.find(item => isMeItem(item));

        if (previewTextEl) {
            if (myItem) {
                const myIdx = currentQueue.indexOf(myItem) + 1;
                const oldNums = ((myItem.lab_number || '').match(/\d+/g) || []).map(Number);
                const oldMin = oldNums.length > 0 ? Math.min(...oldNums) : 999;

                if (minLab > oldMin) {
                    previewTextEl.textContent = `🎯 Обрано: ${labsText} • ⚠️ Пріоритет зміниться на Лабу ${minLab}`;
                } else {
                    previewTextEl.textContent = `🎯 Обрано: ${labsText} • ⭐ Пріоритет: Лаба ${minLab} • 🔒 Місце #${myIdx} збережено`;
                }
            } else {
                previewTextEl.textContent = `🎯 Обрано: ${labsText} • ⭐ Пріоритет: Лаба ${minLab} (найстаріша)`;
            }
        }
        if (priorityPreviewEl) priorityPreviewEl.classList.remove('hidden');
    }

    // Перемикач предметів черги (ОП / АСД)
    function switchQueueSubject(subj) {
        if (subj === activeSubject) return;
        activeSubject = subj;

        if (subj === 'ОП') {
            subjTabOp.classList.add('active');
            subjTabAsd.classList.remove('active');
        } else {
            subjTabAsd.classList.add('active');
            subjTabOp.classList.remove('active');
        }

        if (queueListTitle) queueListTitle.textContent = `Список черги (${activeSubject})`;
        userHasManuallyEditedLabs[activeSubject] = false;
        selectedLabs.clear();
        renderLabsGrid();
        updatePriorityPreview();
        updateBottomButtonState();
        fetchQueue();
        fetchStudentDefenses();
    }

    if (subjTabOp) subjTabOp.addEventListener('click', () => switchQueueSubject('ОП'));
    if (subjTabAsd) subjTabAsd.addEventListener('click', () => switchQueueSubject('АСД'));

    function isMeItem(item) {
        if (!item) return false;
        if (currentUser.id && item.user_id && String(item.user_id) === String(currentUser.id)) return true;
        const cUname = (currentUser.username || '').replace(/^@/, '').toLowerCase().trim();
        const iUname = (item.username || '').replace(/^@/, '').toLowerCase().trim();
        if (cUname && iUname && cUname !== 'student' && cUname === iUname) return true;
        if (currentUser.realName && item.user_name) {
            const surname = currentUser.realName.toLowerCase().trim().split(/\s+/)[0];
            if (surname && item.user_name.toLowerCase().includes(surname)) return true;
        }
        if (currentUser.name && item.user_name) {
            const cName = currentUser.name.toLowerCase().trim();
            const iName = item.user_name.toLowerCase().trim();
            if (cName !== 'студент' && (cName === iName || iName.includes(cName) || cName.includes(iName))) return true;
        }
        return false;
    }

    // Отримання черги
    async function fetchQueue() {
        try {
            const res = await fetch(`/api/queue?subject=${encodeURIComponent(activeSubject)}&chat_id=${chatId}`);
            const data = await res.json();
            if (!data.success) return;

            currentQueue = data.items || [];
            allQueuesData[activeSubject] = currentQueue;
            renderQueueList(currentQueue);

            // Оновлюємо бейджі та міні-картки
            if (activeSubject === 'ОП') {
                if (badgeOpCount) badgeOpCount.textContent = currentQueue.length;
                if (miniOpStat) miniOpStat.textContent = `${currentQueue.length}`;
                if (miniOpSub) miniOpSub.textContent = currentQueue.length > 0 ? `Активна черга 🔥` : `Черга вільна`;
            } else {
                if (badgeAsdCount) badgeAsdCount.textContent = currentQueue.length;
                if (miniAsdStat) miniAsdStat.textContent = `${currentQueue.length}`;
                if (miniAsdSub) miniAsdSub.textContent = currentQueue.length > 0 ? `Активна черга 🔥` : `Черга вільна`;
            }

            const otherSubj = activeSubject === 'ОП' ? 'АСД' : 'ОП';
            fetchOtherQueueCount(otherSubj);

            // Статус користувача в черзі
            const meIndex = currentQueue.findIndex(item => isMeItem(item));
            if (meIndex !== -1) {
                const me = currentQueue[meIndex];
                if (myStatusBox) myStatusBox.classList.remove('hidden');
                if (myPosText) myPosText.textContent = `Ви #${meIndex + 1} у черзі (${activeSubject})!`;
                if (myLabsText) myLabsText.textContent = `${me.lab_number || 'Лаба не вказана'} • ⭐ Пріоритет: Лаба ${me.lab_priority || 1}`;

                // Якщо користувач ще не робив ручного вибору, синхронізуємо обрані лаби з поточної черги
                if (!userHasManuallyEditedLabs[activeSubject]) {
                    selectedLabs.clear();
                    const labMatches = (me.lab_number || '').match(/\d+/g);
                    if (labMatches) {
                        labMatches.forEach(n => selectedLabs.add(parseInt(n, 10)));
                    }
                    renderLabsGrid();
                    updatePriorityPreview();
                }
            } else {
                if (myStatusBox) myStatusBox.classList.add('hidden');
                if (!userHasManuallyEditedLabs[activeSubject]) {
                    selectedLabs.clear();
                    renderLabsGrid();
                    updatePriorityPreview();
                }
            }

            updateBottomButtonState();
            updateHeroSubtitle();
        } catch (err) {
            console.error('Queue fetch error:', err);
        }
    }

    async function fetchOtherQueueCount(subj) {
        try {
            const res = await fetch(`/api/queue?subject=${encodeURIComponent(subj)}&chat_id=${chatId}`);
            const data = await res.json();
            if (data.success) {
                const count = (data.items || []).length;
                allQueuesData[subj] = data.items || [];
                if (subj === 'ОП') {
                    if (badgeOpCount) badgeOpCount.textContent = count;
                    if (miniOpStat) miniOpStat.textContent = `${count}`;
                    if (miniOpSub) miniOpSub.textContent = count > 0 ? `Активна черга 🔥` : `Черга вільна`;
                } else {
                    if (badgeAsdCount) badgeAsdCount.textContent = count;
                    if (miniAsdStat) miniAsdStat.textContent = `${count}`;
                    if (miniAsdSub) miniAsdSub.textContent = count > 0 ? `Активна черга 🔥` : `Черга вільна`;
                }
            }
        } catch (_) {}
    }

    function renderQueueList(items) {
        if (!queueItemsContainer) return;

        if (!items || items.length === 0) {
            queueItemsContainer.innerHTML = '';
            if (queueEmptyEl) queueEmptyEl.classList.remove('hidden');
            return;
        }

        if (queueEmptyEl) queueEmptyEl.classList.add('hidden');
        queueItemsContainer.innerHTML = items.map((item, idx) => {
            const isMe = isMeItem(item);
            const rank = idx + 1;
            const isGold = rank === 1;
            const rankClass = isGold ? 'gold' : '';
            const labBadge = item.lab_number ? `<span class="queue-lab-tag">${escapeHtml(item.lab_number)}</span>` : '';

            return `
                <div class="queue-person-card ${isMe ? 'is-me' : ''}">
                    <div class="queue-rank-badge ${rankClass}">#${rank}</div>
                    <div class="queue-name-col">
                        <span class="queue-name">${escapeHtml(formatQueueName(item.user_name))}${isMe ? ' (Ви)' : ''}</span>
                        <span style="font-size:12px; color:var(--text-muted);">${escapeHtml(item.username ? '@' + item.username : '')}</span>
                    </div>
                    ${labBadge}
                </div>
            `;
        }).join('');
    }

    // Запис у чергу
    async function submitJoinQueue() {
        const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
        if (sorted.length === 0) return;

        const myItem = currentQueue.find(item => isMeItem(item));
        const targetUserId = (myItem && myItem.user_id) ? myItem.user_id : currentUser.id;
        const targetUserName = (myItem && myItem.user_name) ? myItem.user_name : (currentUser.realName || currentUser.name);
        const labLabel = sorted.length === 1 ? `Лаба ${sorted[0]}` : `Лаби ${sorted.join(', ')}`;

        if (btnPrimaryActionText) btnPrimaryActionText.textContent = "⏳ Збереження у черзі...";
        if (btnPrimaryAction) btnPrimaryAction.disabled = true;

        try {
            const res = await fetch('/api/queue/join', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chat_id: chatId,
                    subject: activeSubject,
                    user_id: targetUserId,
                    user_name: targetUserName,
                    username: currentUser.username,
                    lab_number: labLabel,
                    append: false
                })
            });
            const data = await res.json();
            if (data.success) {
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                showToast(`✅ Чергу ${activeSubject} оновлено! (${labLabel})`);
                userHasManuallyEditedLabs[activeSubject] = false;
                await fetchQueue();
            } else {
                showToast(data.message || 'Помилка запису');
            }
        } catch (err) {
            showToast('Помилка з\'єднання з сервером');
        } finally {
            if (btnPrimaryAction) btnPrimaryAction.disabled = false;
            updateBottomButtonState();
        }
    }

    // Вихід з черги
    if (btnLeaveQueue) {
        btnLeaveQueue.addEventListener('click', async () => {
            if (!confirm(`Ви дійсно бажаєте вийти з черги ${activeSubject}?`)) return;
            const myItem = currentQueue.find(item => isMeItem(item));
            const uidToLeave = myItem ? myItem.user_id : currentUser.id;
            try {
                const res = await fetch('/api/queue/leave', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        chat_id: chatId,
                        subject: activeSubject,
                        user_id: uidToLeave,
                        username: currentUser.username
                    })
                });
                const data = await res.json();
                if (data.success) {
                    userHasManuallyEditedLabs[activeSubject] = false;
                    selectedLabs.clear();
                    renderLabsGrid();
                    updatePriorityPreview();
                    updateBottomButtonState();
                    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('warning');
                    showToast(`Ви вийшли з черги ${activeSubject}`);
                    await fetchQueue();
                }
            } catch (err) {
                showToast('Помилка виходу з черги');
            }
        });
    }

    // Перевести наступного
    if (btnNextStudent) {
        btnNextStudent.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/queue/next', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        chat_id: chatId,
                        subject: activeSubject
                    })
                });
                const data = await res.json();
                if (data.success) {
                    if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
                    if (data.student) {
                        showToast(`🎯 Наступний на захист: ${data.student.user_name} (${data.student.lab_number})`, 3500);
                    } else {
                        showToast(`Черга ${activeSubject} порожня!`);
                    }
                    await fetchQueue();
                }
            } catch (err) {
                showToast('Помилка дії');
            }
        });
    }

    // 6. Розклад пар (Сьогодні / Завтра / Тиждень)
    function setScheduleDayTab(mode) {
        scheduleDay = mode;
        const allBtns = [btnDayToday, btnDayTomorrow, btnDayWeek].filter(Boolean);
        allBtns.forEach(b => b.classList.remove('active'));

        if (mode === 'today') {
            if (btnDayToday) btnDayToday.classList.add('active');
            if (scheduleDayTitle) scheduleDayTitle.textContent = 'Розклад на сьогодні';
        } else if (mode === 'tomorrow') {
            if (btnDayTomorrow) btnDayTomorrow.classList.add('active');
            if (scheduleDayTitle) scheduleDayTitle.textContent = 'Розклад на завтра';
        } else if (mode === 'week') {
            if (btnDayWeek) btnDayWeek.classList.add('active');
            if (scheduleDayTitle) scheduleDayTitle.textContent = 'Розклад на тиждень';
        }
        fetchSchedule(mode);
    }

    if (btnDayToday) {
        btnDayToday.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            setScheduleDayTab('today');
        });
    }

    if (btnDayTomorrow) {
        btnDayTomorrow.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            setScheduleDayTab('tomorrow');
        });
    }

    if (btnDayWeek) {
        btnDayWeek.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            setScheduleDayTab('week');
        });
    }

    async function fetchSchedule(mode) {
        if (scheduleLoading) scheduleLoading.classList.remove('hidden');
        if (scheduleItemsContainer) scheduleItemsContainer.innerHTML = '';

        try {
            const res = await fetch(`/api/schedule?day=${mode}`);
            const data = await res.json();
            if (scheduleLoading) scheduleLoading.classList.add('hidden');

            if (!data.success) {
                if (scheduleItemsContainer) {
                    scheduleItemsContainer.innerHTML = '<div style="text-align:center; padding:24px 0; color:var(--text-muted); font-size:14px;">Не вдалося завантажити розклад.</div>';
                }
                return;
            }

            if (mode === 'week') {
                if (scheduleDayTitle && data.week) {
                    scheduleDayTitle.textContent = `Розклад (${data.week}-й тиждень)`;
                }

                if (!data.days || data.days.length === 0) {
                    scheduleItemsContainer.innerHTML = '<div style="text-align:center; padding:24px 0; color:var(--text-muted); font-size:14px;">🎉 На цей тиждень занять немає!</div>';
                    return;
                }

                let html = '';
                data.days.forEach((dayObj, dayIdx) => {
                    const todayBadge = dayObj.is_today ? '<span class="week-today-badge">Сьогодні</span>' : '';
                    html += `
                        <div class="week-day-group">
                            <div class="week-day-header">
                                <span class="week-day-title">📅 ${escapeHtml(dayObj.day_name)} • ${escapeHtml(dayObj.date_formatted)}</span>
                                ${todayBadge}
                            </div>
                    `;

                    if (!dayObj.lessons || dayObj.lessons.length === 0) {
                        html += `<div class="week-day-empty">Занять немає 🎉</div>`;
                    } else {
                        dayObj.lessons.forEach((l, lIdx) => {
                            const linkBadge = l.link_url
                                ? `<span style="color:#7C3AED; font-weight:700; font-size:12px; background:#F3E8FF; padding:3px 9px; border-radius:99px;">🔗 Zoom / Meet</span>`
                                : `<span style="color:var(--text-muted); font-size:11.5px;">Деталі →</span>`;

                            const isCanc = !!l.is_cancelled;
                            const isCustom = !!l.is_custom;
                            const customBadge = isCustom ? '<span class="badge-custom">🟣 Додаткова</span>' : '';
                            const cancBadge = isCanc ? '<span class="badge-cancelled">🚫 Скасовано</span>' : '';
                            const cancReasonHtml = (isCanc && l.cancel_reason) ? `<div class="cancel-reason-callout">⚠️ Причина: ${escapeHtml(l.cancel_reason)}</div>` : '';

                            let adminBarHtml = '';
                            if (currentUser.isAdmin) {
                                const pDate = l.date || dayObj.date;
                                const uncancelBtn = isCanc
                                    ? `<button class="admin-btn admin-btn-restore btn-sched-uncancel" data-pair="${l.pair_number || 1}" data-date="${pDate}">↩️ Відновити</button>`
                                    : `<button class="admin-btn admin-btn-cancel btn-sched-cancel" data-pair="${l.pair_number || 1}" data-date="${pDate}" data-name="${escapeHtml(l.name)}">🚫 Скасувати</button>`;
                                const deleteBtn = isCustom
                                    ? `<button class="admin-btn admin-btn-danger btn-sched-delete" data-custom-id="${l.custom_id}">🗑 Видалити</button>`
                                    : '';
                                adminBarHtml = `<div class="card-admin-bar">${uncancelBtn}${deleteBtn}</div>`;
                            }

                            html += `
                                <div class="task-item-card week-lesson-card ${isCanc ? 'lesson-cancelled' : ''}" data-day="${dayIdx}" data-lesson="${lIdx}" style="cursor:pointer; margin-bottom:8px;">
                                    <div class="task-meta-block">
                                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; flex-wrap:wrap; gap:4px;">
                                            <div style="display:flex; align-items:center; gap:6px;">
                                                <span style="font-size:12.5px; font-weight:700; color:#7C3AED;">Пара ${l.pair_number || 1} • ${l.time || '10:15'} (${l.type || 'Пара'})</span>
                                                ${customBadge}
                                                ${cancBadge}
                                            </div>
                                            ${linkBadge}
                                        </div>
                                        <span class="task-title">${escapeHtml(l.name)}</span>
                                        <span class="task-due-date">👤 ${escapeHtml(l.lecturer || 'Викладач не вказаний')} • ${escapeHtml(formatLocation(l.location))}</span>
                                        ${cancReasonHtml}
                                        ${adminBarHtml}
                                    </div>
                                </div>
                            `;
                        });
                    }
                    html += `</div>`;
                });

                scheduleItemsContainer.innerHTML = html;

                // Клік на картку пари у тижневому режимі
                scheduleItemsContainer.querySelectorAll('.week-lesson-card').forEach(el => {
                    el.addEventListener('click', () => {
                        const dIdx = parseInt(el.getAttribute('data-day'));
                        const lIdx = parseInt(el.getAttribute('data-lesson'));
                        const lesson = data.days[dIdx]?.lessons[lIdx];
                        if (lesson) openLessonModal(lesson);
                    });
                });

                attachScheduleAdminButtonHandlers(scheduleItemsContainer);

            } else {
                // Режим одного дня (today або tomorrow)
                scheduleLessons = data.lessons || [];

                if (scheduleLessons.length === 0) {
                    if (scheduleItemsContainer) {
                        scheduleItemsContainer.innerHTML = '<div style="text-align:center; padding:24px 0; color:var(--text-muted); font-size:14px;">🎉 У цей день пар немає! Відпочивайте.</div>';
                    }
                    return;
                }

                scheduleItemsContainer.innerHTML = scheduleLessons.map((l, idx) => {
                    const linkBadge = l.link_url
                        ? `<span style="color:#7C3AED; font-weight:700; font-size:12.5px; background:#F3E8FF; padding:4px 10px; border-radius:99px;">🔗 Zoom / Meet</span>`
                        : `<span style="color:var(--text-muted); font-size:12px;">Деталі →</span>`;

                    const isCanc = !!l.is_cancelled;
                    const isCustom = !!l.is_custom;
                    const customBadge = isCustom ? '<span class="badge-custom">🟣 Додаткова</span>' : '';
                    const cancBadge = isCanc ? '<span class="badge-cancelled">🚫 Скасовано</span>' : '';
                    const cancReasonHtml = (isCanc && l.cancel_reason) ? `<div class="cancel-reason-callout">⚠️ Причина: ${escapeHtml(l.cancel_reason)}</div>` : '';

                    let adminBarHtml = '';
                    if (currentUser.isAdmin) {
                        const pDate = l.date || (data.date_iso || data.date);
                        const uncancelBtn = isCanc
                            ? `<button class="admin-btn admin-btn-restore btn-sched-uncancel" data-pair="${l.pair_number || 1}" data-date="${pDate}">↩️ Відновити</button>`
                            : `<button class="admin-btn admin-btn-cancel btn-sched-cancel" data-pair="${l.pair_number || 1}" data-date="${pDate}" data-name="${escapeHtml(l.name)}">🚫 Скасувати</button>`;
                        const deleteBtn = isCustom
                            ? `<button class="admin-btn admin-btn-danger btn-sched-delete" data-custom-id="${l.custom_id}">🗑 Видалити</button>`
                            : '';
                        adminBarHtml = `<div class="card-admin-bar">${uncancelBtn}${deleteBtn}</div>`;
                    }

                    return `
                        <div class="task-item-card lesson-clickable-card ${isCanc ? 'lesson-cancelled' : ''}" data-lesson-idx="${idx}" style="cursor:pointer;">
                            <div class="task-meta-block">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; flex-wrap:wrap; gap:4px;">
                                    <div style="display:flex; align-items:center; gap:6px;">
                                        <span style="font-size:12.5px; font-weight:700; color:#7C3AED;">Пара ${l.pair_number || 1} • ${l.time || '10:15'} (${l.type || 'Пара'})</span>
                                        ${customBadge}
                                        ${cancBadge}
                                    </div>
                                    ${linkBadge}
                                </div>
                                <span class="task-title">${escapeHtml(l.name)}</span>
                                <span class="task-due-date">👤 ${escapeHtml(l.lecturer || 'Викладач не вказаний')} • ${escapeHtml(formatLocation(l.location))}</span>
                                ${cancReasonHtml}
                                ${adminBarHtml}
                            </div>
                        </div>
                    `;
                }).join('');

                scheduleItemsContainer.querySelectorAll('.lesson-clickable-card').forEach(el => {
                    el.addEventListener('click', () => {
                        const idx = parseInt(el.getAttribute('data-lesson-idx'));
                        const lesson = scheduleLessons[idx];
                        if (lesson) openLessonModal(lesson);
                    });
                });

                attachScheduleAdminButtonHandlers(scheduleItemsContainer);
            }
            updateHeroSubtitle();
        } catch (err) {
            if (scheduleLoading) scheduleLoading.classList.add('hidden');
            if (scheduleItemsContainer) {
                scheduleItemsContainer.innerHTML = '<div style="text-align:center; padding:24px 0; color:var(--text-muted); font-size:14px;">Помилка завантаження розкладу.</div>';
            }
        }
    }

    // 7. Справжні актуальні дедлайни з Classroom
    async function fetchDeadlines() {
        if (!deadlinesItemsContainer) return;
        try {
            const res = await fetch('/api/deadlines');
            const data = await res.json();
            if (!data.success || !data.deadlines || data.deadlines.length === 0) {
                deadlinesItemsContainer.innerHTML = '<div style="text-align:center; padding:24px 0; color:var(--text-muted); font-size:14px;">✅ Всі актуальні дедлайни закриті! Нових завдань немає.</div>';
                if (deadlinesCountBadge) deadlinesCountBadge.textContent = '0';
                return;
            }

            deadlinesCache = data.deadlines;
            const completedSet = loadCompletedDeadlines();

            // Рахуємо скільки дедлайнів залишилося виконати
            const remainingCount = deadlinesCache.filter(d => {
                const dlKey = String(d.id || `${d.course_id}_${d.title}`);
                return !completedSet.has(dlKey);
            }).length;

            if (deadlinesCountBadge) {
                deadlinesCountBadge.textContent = remainingCount;
            }

            deadlinesItemsContainer.innerHTML = deadlinesCache.map((d, idx) => {
                const dueText = d.due_formatted ? `⏰ Дедлайн: ${d.due_formatted}` : (d.due_time ? `⏰ ${d.due_time}` : 'Без дедлайну');
                const classroomUrl = d.alternate_link || 'https://classroom.google.com';
                const dlKey = String(d.id || `${d.course_id}_${d.title}`);
                const isChecked = completedSet.has(dlKey);

                return `
                    <div class="task-item-card deadline-clickable-card ${isChecked ? 'is-checked' : ''}" data-dl-key="${escapeHtml(dlKey)}" data-dl-idx="${idx}" style="cursor:pointer;">
                        <div class="custom-checkbox">
                            <svg viewBox="0 0 24 24" fill="none">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                        </div>
                        <div class="task-meta-block">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
                                <span class="task-due-date" style="color:#7C3AED; font-weight:800; font-size:11.5px; text-transform:uppercase;">
                                    ${escapeHtml(d.course_clean || d.course_id || 'Курс')}
                                </span>
                                <button class="dl-classroom-link-btn" data-url="${escapeHtml(classroomUrl)}" title="Перейти в Classroom">
                                    Classroom ↗
                                </button>
                            </div>
                            <span class="task-title" style="margin:2px 0;">${escapeHtml(d.title)}</span>
                            <span class="task-due-date">${escapeHtml(dueText)}</span>
                        </div>
                    </div>
                `;
            }).join('');

            // Кнопка швидкого переходу в Classroom на самій картці
            deadlinesItemsContainer.querySelectorAll('.dl-classroom-link-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const url = btn.getAttribute('data-url');
                    if (url) {
                        if (tg?.openLink) {
                            tg.openLink(url);
                        } else {
                            window.open(url, '_blank');
                        }
                    }
                });
            });

            // Клік по чекбоксу відмічає виконання та зберігає в localStorage
            deadlinesItemsContainer.querySelectorAll('.deadline-clickable-card').forEach(el => {
                const checkbox = el.querySelector('.custom-checkbox');
                if (checkbox) {
                    checkbox.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const isNowChecked = el.classList.toggle('is-checked');
                        const dlKey = el.getAttribute('data-dl-key');
                        if (dlKey) {
                            const set = loadCompletedDeadlines();
                            if (isNowChecked) {
                                set.add(dlKey);
                                showToast('Дедлайн позначено як виконаний! ✅');
                            } else {
                                set.delete(dlKey);
                                showToast('Дедлайн повернуто в активні');
                            }
                            saveCompletedDeadlines(set);

                            // Оновлюємо лічильник незакритих завдань
                            if (deadlinesCountBadge && deadlinesCache.length > 0) {
                                const remaining = deadlinesCache.filter(d => {
                                    const k = String(d.id || `${d.course_id}_${d.title}`);
                                    return !set.has(k);
                                }).length;
                                deadlinesCountBadge.textContent = remaining;
                            }
                        }
                        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
                    });
                }
                el.addEventListener('click', () => {
                    const idx = parseInt(el.getAttribute('data-dl-idx'));
                    const dl = deadlinesCache[idx];
                    if (dl) {
                        const targetUrl = dl.alternate_link || 'https://classroom.google.com';
                        const currentSet = loadCompletedDeadlines();
                        const dlKey = String(dl.id || `${dl.course_id}_${dl.title}`);
                        const isDone = currentSet.has(dlKey);
                        const statusBadge = isDone
                            ? '<span style="display:inline-block; background:#DCFCE7; color:#166534; font-size:12px; font-weight:700; padding:4px 10px; border-radius:8px; margin-bottom:10px;">✅ Виконано (відмічено галочкою)</span>'
                            : '<span style="display:inline-block; background:#FEF3C7; color:#92400E; font-size:12px; font-weight:700; padding:4px 10px; border-radius:8px; margin-bottom:10px;">⏳ В процесі виконання</span>';

                        openModal({
                            tag: dl.course_clean || dl.course_id || 'Завдання Classroom',
                            title: dl.title,
                            time: dl.due_formatted ? `⏰ Дедлайн: ${dl.due_formatted}` : 'Без дедлайну',
                            body: `
                                ${statusBadge}
                                ${dl.ai_summary ? `<div style="background:#F3E8FF; padding:10px 14px; border-radius:14px; margin-bottom:12px; font-size:13.5px; color:#581C87; line-height:1.4;"><b>💡 Короткий зміст (AI):</b><br>${escapeHtml(dl.ai_summary)}</div>` : ''}
                                ${dl.description ? `<div style="font-size:13px; color:#475569; max-height:140px; overflow-y:auto; line-height:1.4;">${escapeHtml(dl.description)}</div>` : ''}
                            `,
                            linkUrl: targetUrl,
                            linkText: '🚀 Перейти в Classroom'
                        });
                    }
                });
            });

            updateHeroSubtitle();
        } catch (err) {
            deadlinesItemsContainer.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-muted);">Не вдалося завантажити дедлайни</div>';
        }
    }

    // --- 8. Навчальні предмети (ОП Практикуми / АСД Практичні роботи) ---
    function getSubjectTerminology(subj) {
        if (subj === 'ОП') {
            return {
                code: 'ОП',
                title: 'Основи програмування',
                termSingular: 'Практикум',
                termPlural: 'Практикуми',
                totalWorks: 8,
                emoji: '💻',
                themeClass: ''
            };
        } else {
            return {
                code: 'АСД',
                title: 'Алгоритми та структури даних',
                termSingular: 'Практична',
                termPlural: 'Практичні роботи',
                totalWorks: 8,
                emoji: '🧮',
                themeClass: 'asd-theme'
            };
        }
    }

    function getStudentProgressKey(studentName, subj) {
        const cleanName = (studentName || currentUser?.name || 'student').trim().toLowerCase();
        return `ip66_subj_progress_${cleanName}_${subj}`;
    }

    function loadStudentLocalProgress(studentName, subj) {
        try {
            const raw = localStorage.getItem(getStudentProgressKey(studentName, subj));
            if (raw === null) return null;
            const arr = JSON.parse(raw);
            return new Set(Array.isArray(arr) ? arr.map(Number) : []);
        } catch (_) {
            return new Set();
        }
    }

    function saveStudentLocalProgress(studentName, subj, numSet) {
        try {
            const arr = Array.from(numSet);
            localStorage.setItem(getStudentProgressKey(studentName, subj), JSON.stringify(arr));
        } catch (_) {}
    }

    async function fetchSubjectsOverview() {
        try {
            const res = await fetch('/api/subjects/overview');
            const data = await res.json();
            if (data.success) {
                subjectsOverviewData = data;
                renderSubjectsView();
            }
        } catch (err) {
            console.error('Failed to fetch subjects overview', err);
        }
    }

    function renderSubjectsView() {
        const meta = getSubjectTerminology(activeSubjectsSubj);

        // Перемикач шапки картки
        if (subjectProgressHero) {
            if (meta.themeClass) {
                subjectProgressHero.classList.add(meta.themeClass);
            } else {
                subjectProgressHero.classList.remove('asd-theme');
            }
        }
        if (subjectHeroTitle) subjectHeroTitle.textContent = meta.title;
        if (subjectHeroTerm) subjectHeroTerm.textContent = `${meta.termPlural} (1-${meta.totalWorks})`;

        renderMyProgressView(meta);
    }

    function renderMyProgressView(meta) {
        if (!subjectWorksContainer) return;

        const myName = currentUser?.name || 'Студент';
        const myRealName = currentUser?.realName || myName;
        const myTgId = currentUser?.id;

        // Збираємо офіційно зафіксовані захисти з бази даних
        const officialDefenses = new Map();
        (subjectsOverviewData?.defenses || []).forEach(d => {
            const isMatch = (myTgId && d.telegram_id === myTgId) ||
                            (d.real_name && (d.real_name.toLowerCase() === myName.toLowerCase() || d.real_name.toLowerCase() === myRealName.toLowerCase()));
            if (isMatch && d.subject === meta.code) {
                const matchNum = (d.lab_number || '').match(/\d+/);
                if (matchNum) {
                    const n = parseInt(matchNum[0]);
                    officialDefenses.set(n, d);
                }
            }
        });

        // Завантажуємо локальний стан студента з localStorage
        let localSet = loadStudentLocalProgress(myName, meta.code);
        if (localSet === null) {
            // Перший запуск: ініціалізуємо даними з бази, якщо такі є
            localSet = new Set();
            for (const n of officialDefenses.keys()) {
                localSet.add(n);
            }
            saveStudentLocalProgress(myName, meta.code, localSet);
        }

        // Підрахунок прогресу
        const passedCount = Array.from(localSet).filter(n => n >= 1 && n <= meta.totalWorks).length;
        const percent = Math.round((passedCount / meta.totalWorks) * 100);

        if (subjectScoreBadge) subjectScoreBadge.textContent = `${passedCount} / ${meta.totalWorks}`;
        if (subjectProgressBarFill) subjectProgressBarFill.style.width = `${percent}%`;
        if (subjectProgressPercent) subjectProgressPercent.textContent = `${percent}% здано`;
        if (subjectProgressStatus) {
            if (passedCount === meta.totalWorks) {
                subjectProgressStatus.textContent = '🎉 Всі роботи складено!';
            } else if (passedCount > 0) {
                subjectProgressStatus.textContent = `Залишилося: ${meta.totalWorks - passedCount}`;
            } else {
                subjectProgressStatus.textContent = 'Очікує виконання';
            }
        }

        let html = '';
        for (let i = 1; i <= meta.totalWorks; i++) {
            const isPassed = localSet.has(i);
            const officialDef = officialDefenses.get(i);
            // Лише справжні записи з відеозаписів викладачів мають video_id != 'manual'
            const isAiDefense = isPassed && officialDef && officialDef.video_id && officialDef.video_id !== 'manual';

            let badgeHtml = '';
            let quoteHtml = '';

            if (isAiDefense) {
                badgeHtml = '<span class="work-status-badge ai-video">🎥 Здано на парі (AI)</span>';
                if (officialDef.exact_quote) {
                    quoteHtml = `<div class="work-quote-snippet">💬 «${escapeHtml(officialDef.exact_quote)}»</div>`;
                }
            } else if (isPassed) {
                badgeHtml = '<span class="work-status-badge passed">✅ Здано</span>';
            } else {
                badgeHtml = '<span class="work-status-badge pending">⏳ Не здано</span>';
            }

            html += `
                <div class="work-item-card ${isPassed ? 'is-passed' : ''}" data-work-num="${i}">
                    <div class="custom-checkbox ${isPassed ? 'checked' : ''}" style="${isPassed ? 'background:#16A34A; border-color:#16A34A;' : ''}">
                        <svg viewBox="0 0 24 24" fill="none" style="${isPassed ? 'display:block; stroke:#FFFFFF; stroke-width:3.5;' : 'display:none;'}">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                    </div>
                    <div class="work-meta-block">
                        <div class="work-title-row">
                            <div class="work-title-badge-wrap">
                                <span class="work-term-title">${escapeHtml(meta.termSingular)}</span>
                                <span class="work-num-pill">№ ${i}</span>
                            </div>
                            ${badgeHtml}
                        </div>
                        ${quoteHtml}
                    </div>
                </div>
            `;
        }

        subjectWorksContainer.innerHTML = html;

        subjectWorksContainer.querySelectorAll('.work-item-card').forEach(card => {
            card.addEventListener('click', () => {
                const num = parseInt(card.getAttribute('data-work-num'));
                toggleStudentWork(myName, currentUser?.id, meta.code, num);
            });
        });
    }

    async function toggleStudentWork(studentName, studentTgId, subj, workNum) {
        const meta = getSubjectTerminology(subj);
        const workTitle = `${meta.termSingular} № ${workNum}`;
        let set = loadStudentLocalProgress(studentName, subj);
        if (set === null) set = new Set();

        let isNowPassed = false;
        if (set.has(workNum)) {
            set.delete(workNum);
            isNowPassed = false;
            showToast(`${workTitle}: відмітку знято`);

            // Видаляємо з локального кешу defenses, щоб не перевідкривалося при перерендері
            if (subjectsOverviewData && Array.isArray(subjectsOverviewData.defenses)) {
                subjectsOverviewData.defenses = subjectsOverviewData.defenses.filter(d => {
                    const matchNum = (d.lab_number || '').match(/\d+/);
                    const n = matchNum ? parseInt(matchNum[0]) : null;
                    const isSameSubj = d.subject === subj;
                    const isMe = (studentTgId && d.telegram_id === studentTgId) ||
                                 (d.real_name && d.real_name.toLowerCase() === studentName.toLowerCase());
                    return !(isSameSubj && isMe && n === workNum);
                });
            }
        } else {
            set.add(workNum);
            isNowPassed = true;
            showToast(`✅ ${workTitle} зараховано!`);

            // Додаємо в локальний кеш defenses
            if (subjectsOverviewData && Array.isArray(subjectsOverviewData.defenses)) {
                subjectsOverviewData.defenses.push({
                    real_name: studentName,
                    telegram_id: studentTgId,
                    subject: subj,
                    lab_number: workTitle,
                    video_id: 'manual',
                    exact_quote: '',
                    status: 'passed',
                    confirmed: 1
                });
            }
        }

        saveStudentLocalProgress(studentName, subj, set);
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');

        // Миттєвий перерендер UI
        renderSubjectsView();

        // Оновлюємо статус у черзі вибору лаб, якщо це той самий предмет
        if (activeSubject === subj) {
            renderLabsGrid();
        }

        // Фонова синхронізація з базою даних
        try {
            await fetch('/api/defenses/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    real_name: currentUser?.realName || studentName,
                    subject: subj,
                    lab_number: `${meta.termSingular} ${workNum}`,
                    user_id: studentTgId || null
                })
            });
        } catch (_) {}
    }

    // Слухачі подій перемикання дисциплін (ОП vs АСД)
    if (subjectsTabOp) {
        subjectsTabOp.addEventListener('click', () => {
            activeSubjectsSubj = 'ОП';
            subjectsTabOp.classList.add('active');
            subjectsTabAsd.classList.remove('active');
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            renderSubjectsView();
            updateBottomButtonState();
        });
    }
    if (subjectsTabAsd) {
        subjectsTabAsd.addEventListener('click', () => {
            activeSubjectsSubj = 'АСД';
            subjectsTabAsd.classList.add('active');
            subjectsTabOp.classList.remove('active');
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            renderSubjectsView();
            updateBottomButtonState();
        });
    }

    function updateHeroSubtitle() {
        if (!heroSubtitleEl) return;
        heroSubtitleEl.textContent = 'Група ІП-66 • ФІОТ';
    }

    async function refreshAllData() {
        await Promise.all([
            fetchQueue(),
            fetchSchedule(scheduleDay),
            fetchDeadlines(),
            fetchStudentDefenses(),
            fetchSubjectsOverview()
        ]);
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ==========================================
    // ⚙️ АДМІН-ПАНЕЛЬ (ВЛАСНИК, СТАРОСТА, ЗАМСТАРОСТИ)
    // ==========================================

    function getKyivDateString(offsetDays = 0) {
        const d = new Date();
        d.setDate(d.getDate() + offsetDays);
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    async function handleAdminCancelPair(date, pairNum, subject) {
        const reason = prompt(`Вкажіть причину скасування пари №${pairNum} на ${date}:`, "Скасовано викладачем/старостою");
        if (reason === null) return;
        try {
            const res = await fetch('/api/admin/schedule/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: currentUser.id,
                    username: currentUser.username,
                    date: date,
                    pair_number: parseInt(pairNum),
                    subject: subject || '',
                    reason: reason.trim() || 'Скасовано викладачем/старостою',
                    admin_name: currentUser.realName || currentUser.name
                })
            });
            const data = await res.json();
            if (data.success) {
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                showToast(`🚫 Пару №${pairNum} скасовано!`);
                fetchSchedule(scheduleDay);
                const adminDateEl = document.getElementById('admin-schedule-date');
                if (adminDateEl && typeof loadAdminScheduleDate === 'function') {
                    loadAdminScheduleDate(adminDateEl.value || date);
                }
            } else {
                showToast(data.error || 'Помилка скасування');
            }
        } catch (_) {
            showToast("Помилка з'єднання");
        }
    }

    async function handleAdminUncancelPair(date, pairNum) {
        try {
            const res = await fetch('/api/admin/schedule/uncancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: currentUser.id,
                    username: currentUser.username,
                    date: date,
                    pair_number: parseInt(pairNum)
                })
            });
            const data = await res.json();
            if (data.success) {
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                showToast(`✅ Скасування пари №${pairNum} знято!`);
                fetchSchedule(scheduleDay);
                const adminDateEl = document.getElementById('admin-schedule-date');
                if (adminDateEl && typeof loadAdminScheduleDate === 'function') {
                    loadAdminScheduleDate(adminDateEl.value || date);
                }
            } else {
                showToast(data.error || 'Помилка');
            }
        } catch (_) {
            showToast("Помилка з'єднання");
        }
    }

    async function handleAdminDeletePair(customId) {
        if (!confirm("Видалити цю додаткову пару з розкладу?")) return;
        try {
            const res = await fetch('/api/admin/schedule/delete_pair', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: currentUser.id,
                    username: currentUser.username,
                    id: parseInt(customId)
                })
            });
            const data = await res.json();
            if (data.success) {
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                showToast("🗑 Додаткову пару успішно видалено!");
                fetchSchedule(scheduleDay);
                const adminDateEl = document.getElementById('admin-schedule-date');
                if (adminDateEl && typeof loadAdminScheduleDate === 'function') {
                    loadAdminScheduleDate(adminDateEl.value || getKyivDateString(0));
                }
            } else {
                showToast(data.error || 'Помилка');
            }
        } catch (_) {
            showToast("Помилка з'єднання");
        }
    }

    function attachScheduleAdminButtonHandlers(container) {
        if (!container) return;
        container.querySelectorAll('.btn-sched-cancel').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const pNum = btn.getAttribute('data-pair');
                const pDate = btn.getAttribute('data-date');
                const pName = btn.getAttribute('data-name');
                handleAdminCancelPair(pDate, pNum, pName);
            });
        });

        container.querySelectorAll('.btn-sched-uncancel').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const pNum = btn.getAttribute('data-pair');
                const pDate = btn.getAttribute('data-date');
                handleAdminUncancelPair(pDate, pNum);
            });
        });

        container.querySelectorAll('.btn-sched-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const customId = btn.getAttribute('data-custom-id');
                handleAdminDeletePair(customId);
            });
        });
    }

    async function loadAdminScheduleDate(dateStr) {
        const listEl = document.getElementById('admin-schedule-list');
        if (!listEl) return;
        listEl.innerHTML = '<div style="text-align:center; padding:12px; color:var(--text-muted); font-size:12.5px;">Завантаження пар...</div>';

        try {
            const res = await fetch(`/api/schedule?date=${encodeURIComponent(dateStr)}`);
            const data = await res.json();
            if (!data.success || !data.lessons || data.lessons.length === 0) {
                listEl.innerHTML = '<div style="text-align:center; padding:14px; color:var(--text-muted); font-size:13px;">🎉 На цю дату занять немає</div>';
                return;
            }

            listEl.innerHTML = data.lessons.map(l => {
                const isCanc = !!l.is_cancelled;
                const isCustom = !!l.is_custom;
                const customBadge = isCustom ? '<span class="badge-custom">🟣 Додаткова</span>' : '';
                const cancBadge = isCanc ? '<span class="badge-cancelled">🚫 Скасовано</span>' : '';
                const cancReason = (isCanc && l.cancel_reason) ? `<div class="cancel-reason-callout">⚠️ Причина: ${escapeHtml(l.cancel_reason)}</div>` : '';

                const badgesRowHtml = (isCustom || isCanc)
                    ? `<div class="admin-card-badges">${customBadge}${cancBadge}</div>`
                    : '';

                const actionBtn = isCanc
                    ? `<button class="admin-btn admin-btn-restore btn-admin-act-uncancel" data-pair="${l.pair_number}">↩️ Відновити</button>`
                    : `<button class="admin-btn admin-btn-cancel btn-admin-act-cancel" data-pair="${l.pair_number}" data-name="${escapeHtml(l.name)}">🚫 Скасувати</button>`;

                const deleteBtn = isCustom
                    ? `<button class="admin-btn admin-btn-danger btn-admin-act-delete" data-id="${l.custom_id}">🗑 Видалити</button>`
                    : '';

                const linkInfo = l.link_url
                    ? `<a href="${escapeHtml(l.link_url)}" target="_blank" style="color:#7C3AED; font-weight:600; text-decoration:none; display:inline-flex; align-items:center; gap:3px;">🔗 Zoom / Meet</a>`
                    : '';

                return `
                    <div class="admin-lesson-card ${isCanc ? 'lesson-cancelled' : ''}">
                        <div class="admin-card-head">
                            <span class="admin-card-time">Пара ${l.pair_number} • ${l.time} (${escapeHtml(l.type || 'Пара')})</span>
                            <div class="admin-card-actions">
                                ${actionBtn}
                                ${deleteBtn}
                            </div>
                        </div>
                        ${badgesRowHtml}
                        <div class="admin-card-title">${escapeHtml(l.name)}</div>
                        <div class="admin-card-footer">
                            <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
                                <span>👤 ${escapeHtml(l.lecturer || 'Викладач не вказаний')}</span>
                                ${linkInfo}
                            </div>
                            ${cancReason}
                        </div>
                    </div>
                `;
            }).join('');

            listEl.querySelectorAll('.btn-admin-act-cancel').forEach(btn => {
                btn.addEventListener('click', () => {
                    const pNum = btn.getAttribute('data-pair');
                    const name = btn.getAttribute('data-name');
                    handleAdminCancelPair(dateStr, pNum, name);
                });
            });

            listEl.querySelectorAll('.btn-admin-act-uncancel').forEach(btn => {
                btn.addEventListener('click', () => {
                    const pNum = btn.getAttribute('data-pair');
                    handleAdminUncancelPair(dateStr, pNum);
                });
            });

            listEl.querySelectorAll('.btn-admin-act-delete').forEach(btn => {
                btn.addEventListener('click', () => {
                    const id = btn.getAttribute('data-id');
                    handleAdminDeletePair(id);
                });
            });

        } catch (e) {
            listEl.innerHTML = '<div style="text-align:center; padding:12px; color:var(--text-muted); font-size:12.5px;">Помилка завантаження розкладу</div>';
        }
    }

    async function populateAdminStudentDropdown() {
        const sel = document.getElementById('admin-student-select');
        if (!sel) return;
        try {
            const res = await fetch('/api/students');
            const data = await res.json();
            if (data.students && Array.isArray(data.students)) {
                sel.innerHTML = '<option value="">Оберіть студента зі списку групи...</option>' +
                    data.students.map(s => {
                        const uname = s.telegram_username ? `@${escapeHtml(s.telegram_username)}` : 'без username';
                        return `<option value="${s.telegram_id || ''}" data-username="${escapeHtml(s.telegram_username || '')}" data-realname="${escapeHtml(s.real_name)}">
                            ${escapeHtml(s.real_name)} (${uname})
                        </option>`;
                    }).join('');
            }
        } catch (_) {}
    }

    function renderAdminRolesList(roles) {
        const listEl = document.getElementById('admin-roles-list');
        if (!listEl) return;
        if (!roles || roles.length === 0) {
            listEl.innerHTML = '<div style="font-size:12px; color:var(--text-muted); padding:8px 0;">Призначених адміністраторів ще немає. Власник завжди має повний доступ.</div>';
            return;
        }

        listEl.innerHTML = roles.map(r => {
            const isHeadman = r.role === 'headman';
            const roleClass = isHeadman ? 'headman' : 'deputy';
            const roleTitle = isHeadman ? 'Староста' : 'Замстарости';
            const uname = r.username ? `@${escapeHtml(r.username)}` : (r.user_id ? `ID: ${r.user_id}` : '');
            return `
                <div class="admin-role-item">
                    <div>
                        <div style="font-weight:700; color:var(--text-primary);">${escapeHtml(r.real_name || r.username || 'Адміністратор')}</div>
                        <div style="font-size:11.5px; color:var(--text-muted);">${uname} • <span class="admin-role-badge ${roleClass}">${roleTitle}</span></div>
                    </div>
                    <button class="admin-btn admin-btn-danger btn-admin-revoke-role" data-role-id="${r.id}" style="padding:4px 9px; font-size:11px;">
                        ❌ Зняти
                    </button>
                </div>
            `;
        }).join('');

        listEl.querySelectorAll('.btn-admin-revoke-role').forEach(btn => {
            btn.addEventListener('click', async () => {
                const roleId = btn.getAttribute('data-role-id');
                if (!confirm("Зняти права адміністратора з цього користувача?")) return;
                try {
                    const res = await fetch('/api/admin/roles/revoke', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            user_id: currentUser.id,
                            username: currentUser.username,
                            role_id: parseInt(roleId)
                        })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast("Права скасовано");
                        renderAdminRolesList(data.roles);
                    } else {
                        showToast(data.error || 'Помилка');
                    }
                } catch (_) {
                    showToast("Помилка з'єднання");
                }
            });
        });
    }

    async function fetchAdminStatus() {
        try {
            const uid = currentUser.id || '';
            const uname = encodeURIComponent(currentUser.username || '');
            const res = await fetch(`/api/admin/me?user_id=${uid}&username=${uname}`);
            const data = await res.json();
            if (data.success && data.is_admin) {
                currentUser.isAdmin = true;
                currentUser.isOwner = !!data.is_owner;
                currentUser.adminRole = data.role;
                currentUser.testMode = !!data.test_mode;

                const navBtnAdmin = document.getElementById('nav-btn-admin');
                if (navBtnAdmin) navBtnAdmin.classList.remove('hidden');

                const roleBadge = document.getElementById('admin-role-badge');
                if (roleBadge) {
                    if (data.is_owner) {
                        roleBadge.innerHTML = '👑 <b>Власник бота</b> (повний доступ до всіх функцій)';
                    } else if (data.role === 'headman') {
                        roleBadge.innerHTML = '⭐️ <b>Староста групи</b>';
                    } else {
                        roleBadge.innerHTML = '🛡 <b>Заступник старости</b>';
                    }
                }

                const testModeCard = document.getElementById('admin-test-mode-card');
                const testModeToggle = document.getElementById('admin-test-mode-toggle');
                const testModeDesc = document.getElementById('admin-test-mode-desc');
                if (testModeCard && data.is_owner) {
                    testModeCard.classList.remove('hidden');
                    if (testModeToggle) {
                        testModeToggle.checked = !!data.test_mode;
                        testModeToggle.onchange = async () => {
                            try {
                                const newMode = testModeToggle.checked;
                                const r = await fetch('/api/admin/test_mode', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        user_id: currentUser.id,
                                        username: currentUser.username,
                                        test_mode: newMode
                                    })
                                });
                                const d = await r.json();
                                if (d.success) {
                                    if (testModeDesc) {
                                        testModeDesc.textContent = newMode
                                            ? 'Адмінку бачите тільки ви. Доступ для старости та замів заблоковано.'
                                            : 'Доступ до адмінки відкрито для призначених старости та замів.';
                                    }
                                    showToast(newMode ? '🔒 Особистий тест-режим увімкнено' : '🔓 Доступ відкрито для старостату');
                                }
                            } catch (_) {
                                showToast('Помилка зміни тест-режиму');
                            }
                        };
                    }
                    if (testModeDesc) {
                        testModeDesc.textContent = data.test_mode
                            ? 'Адмінку бачите тільки ви. Доступ для старости та замів заблоковано.'
                            : 'Доступ до адмінки відкрито для призначених старости та замів.';
                    }
                }

                renderAdminRolesList(data.roles || []);
                populateAdminStudentDropdown();

                // Re-render schedule to attach admin action buttons on cards
                fetchSchedule(scheduleDay);
            } else {
                currentUser.isAdmin = false;
                currentUser.isOwner = false;
            }
        } catch (e) {
            console.error('Failed to check admin status:', e);
        }
    }

    function initAdminPanelControls() {
        const adminDateInput = document.getElementById('admin-schedule-date');
        const btnDateToday = document.getElementById('btn-admin-date-today');
        const btnDateTomorrow = document.getElementById('btn-admin-date-tomorrow');
        const btnAddPair = document.getElementById('btn-admin-add-pair');
        const btnGrantRole = document.getElementById('btn-admin-grant-role');

        const todayStr = getKyivDateString(0);
        const tomorrowStr = getKyivDateString(1);

        if (adminDateInput) {
            adminDateInput.value = todayStr;
            adminDateInput.addEventListener('change', () => {
                if (btnDateToday) btnDateToday.classList.toggle('active', adminDateInput.value === todayStr);
                if (btnDateTomorrow) btnDateTomorrow.classList.toggle('active', adminDateInput.value === tomorrowStr);
                loadAdminScheduleDate(adminDateInput.value);
            });
        }

        if (btnDateToday && adminDateInput) {
            btnDateToday.addEventListener('click', () => {
                adminDateInput.value = todayStr;
                btnDateToday.classList.add('active');
                if (btnDateTomorrow) btnDateTomorrow.classList.remove('active');
                loadAdminScheduleDate(todayStr);
            });
        }

        if (btnDateTomorrow && adminDateInput) {
            btnDateTomorrow.addEventListener('click', () => {
                adminDateInput.value = tomorrowStr;
                btnDateTomorrow.classList.add('active');
                if (btnDateToday) btnDateToday.classList.remove('active');
                loadAdminScheduleDate(tomorrowStr);
            });
        }

        // Add Pair Submit
        if (btnAddPair && adminDateInput) {
            btnAddPair.addEventListener('click', async () => {
                const pairNum = parseInt(document.getElementById('admin-pair-num')?.value) || 1;
                const pairType = document.getElementById('admin-pair-type')?.value || 'Практика';
                const pairName = document.getElementById('admin-pair-name')?.value?.trim();
                const lecturer = document.getElementById('admin-pair-lecturer')?.value?.trim() || '';
                const linkUrl = document.getElementById('admin-pair-link')?.value?.trim() || '';
                const comment = document.getElementById('admin-pair-comment')?.value?.trim() || '';

                if (!pairName) {
                    showToast('Вкажіть назву дисципліни!');
                    document.getElementById('admin-pair-name')?.focus();
                    return;
                }

                try {
                    const res = await fetch('/api/admin/schedule/add_pair', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            user_id: currentUser.id,
                            username: currentUser.username,
                            date: adminDateInput.value,
                            pair_number: pairNum,
                            name: pairName,
                            type: pairType,
                            lecturer: lecturer,
                            link_url: linkUrl,
                            comment: comment,
                            admin_name: currentUser.realName || currentUser.name
                        })
                    });
                    const data = await res.json();
                    if (data.success) {
                        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                        showToast('✅ Пару успішно додано в розклад!');
                        const nameEl = document.getElementById('admin-pair-name');
                        const lectEl = document.getElementById('admin-pair-lecturer');
                        const linkEl = document.getElementById('admin-pair-link');
                        const commEl = document.getElementById('admin-pair-comment');
                        if (nameEl) nameEl.value = '';
                        if (lectEl) lectEl.value = '';
                        if (linkEl) linkEl.value = '';
                        if (commEl) commEl.value = '';

                        loadAdminScheduleDate(adminDateInput.value);
                        fetchSchedule(scheduleDay);
                    } else {
                        showToast(data.error || 'Помилка додавання пари');
                    }
                } catch (_) {
                    showToast("Помилка з'єднання");
                }
            });
        }

        // Grant Admin Role
        if (btnGrantRole) {
            btnGrantRole.addEventListener('click', async () => {
                const studentSel = document.getElementById('admin-student-select');
                const customUnameInput = document.getElementById('admin-custom-username');
                const roleSel = document.getElementById('admin-role-select');

                const selectedOption = studentSel?.selectedOptions?.[0];
                let targetUid = selectedOption ? selectedOption.value : '';
                let targetUname = customUnameInput?.value?.trim()?.replace(/^@/, '') || '';
                let targetRealName = selectedOption ? (selectedOption.getAttribute('data-realname') || '') : '';

                if (!targetUname && selectedOption) {
                    targetUname = selectedOption.getAttribute('data-username') || '';
                }

                if (!targetUid && !targetUname) {
                    showToast('Оберіть студента або введіть @username!');
                    return;
                }

                const role = roleSel?.value || 'deputy';

                try {
                    const res = await fetch('/api/admin/roles/grant', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            user_id: currentUser.id,
                            username: currentUser.username,
                            target_user_id: targetUid ? parseInt(targetUid) : null,
                            target_username: targetUname || null,
                            target_real_name: targetRealName,
                            role: role
                        })
                    });
                    const data = await res.json();
                    if (data.success) {
                        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                        showToast('✅ Права адміністратора надано!');
                        if (customUnameInput) customUnameInput.value = '';
                        if (studentSel) studentSel.value = '';
                        renderAdminRolesList(data.roles);
                    } else {
                        showToast(data.error || 'Помилка');
                    }
                } catch (_) {
                    showToast("Помилка з'єднання");
                }
            });
        }

        // Quick Queue Buttons
        const btnNextOp = document.getElementById('btn-admin-next-op');
        const btnClearOp = document.getElementById('btn-admin-clear-op');
        const btnNextAsd = document.getElementById('btn-admin-next-asd');
        const btnClearAsd = document.getElementById('btn-admin-clear-asd');

        if (btnNextOp) btnNextOp.addEventListener('click', () => adminQueueActionNext('ОП'));
        if (btnClearOp) btnClearOp.addEventListener('click', () => adminQueueActionClear('ОП'));
        if (btnNextAsd) btnNextAsd.addEventListener('click', () => adminQueueActionNext('АСД'));
        if (btnClearAsd) btnClearAsd.addEventListener('click', () => adminQueueActionClear('АСД'));
    }

    async function adminQueueActionNext(subj) {
        try {
            const res = await fetch('/api/queue/next', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_id: chatId, subject: subj })
            });
            const data = await res.json();
            if (data.success) {
                if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
                if (data.student) {
                    showToast(`🎯 Наступний (${subj}): ${data.student.user_name} (${data.student.lab_number})`, 3500);
                } else {
                    showToast(`Черга ${subj} порожня!`);
                }
                await fetchQueue();
            }
        } catch (_) {
            showToast('Помилка дії');
        }
    }

    async function adminQueueActionClear(subj) {
        if (!confirm(`Ви впевнені, що хочете повністю очистити чергу ${subj}?`)) return;
        try {
            const res = await fetch('/api/admin/queue/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: currentUser.id,
                    username: currentUser.username,
                    chat_id: chatId,
                    subject: subj
                })
            });
            const data = await res.json();
            if (data.success) {
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                showToast(data.message || `Чергу ${subj} очищено`);
                await fetchQueue();
            } else {
                showToast(data.error || 'Помилка');
            }
        } catch (_) {
            showToast("Помилка з'єднання");
        }
    }

    // Первинний запуск
    renderLabsGrid();
    updatePriorityPreview();
    updateBottomButtonState();
    initAdminPanelControls();
    fetchAdminStatus();
    refreshAllData();

    // Автоматичне фонове оновлення черги кожні 4 секунди
    pollInterval = setInterval(() => {
        if (currentTab === 'tab-queue') {
            fetchQueue();
        }
    }, 4000);
});
