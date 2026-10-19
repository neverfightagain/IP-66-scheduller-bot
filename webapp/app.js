// --- Telegram Mini App Frontend Controller (ІП-66 Портал) ---
document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
        tg.ready();
        tg.expand();
    }

    // Інформація про користувача з Telegram WebApp SDK
    const tgUser = tg?.initDataUnsafe?.user;
    const currentUser = {
        id: tgUser?.id || 999001,
        name: tgUser ? [tgUser.first_name, tgUser.last_name].filter(Boolean).join(' ') : 'Студент',
        firstName: tgUser?.first_name || 'Студент',
        username: tgUser?.username || 'student'
    };

    // Параметри URL від бота (chat_id, subject)
    const urlParams = new URLSearchParams(window.location.search);
    const chatId = parseInt(urlParams.get('chat_id')) || 0;
    const initialSubject = (urlParams.get('subject') || 'ОП').toUpperCase();

    // Стан додатку
    let activeSubject = ['ОП', 'АСД'].includes(initialSubject) ? initialSubject : 'ОП';
    let selectedLabs = new Set();
    let currentQueue = [];
    let allQueuesData = { 'ОП': [], 'АСД': [] };
    let scheduleLessons = [];
    let scheduleDay = 'today';
    let currentTab = 'tab-queue'; // Фокус на черзі!
    let pollInterval = null;

    // DOM Elements
    const btnCloseApp = document.getElementById('btn-close-app');
    const userGreetingEl = document.getElementById('user-greeting');
    const heroSubtitleEl = document.getElementById('hero-subtitle');
    const btnAvatarBadge = document.getElementById('btn-avatar-badge');
    const btnSync = document.getElementById('btn-sync');

    // Featured Card
    const featuredCard = document.getElementById('featured-card');
    const featuredStatusTag = document.getElementById('featured-status-tag');
    const featuredTimePill = document.getElementById('featured-time-pill');
    const featuredCardTitle = document.getElementById('featured-card-title');
    const featuredCardMeta = document.getElementById('featured-card-meta');

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
    const scheduleItemsContainer = document.getElementById('schedule-items-container');
    const scheduleLoading = document.getElementById('schedule-loading');
    const scheduleDayTitle = document.getElementById('schedule-day-title');

    // Deadlines Elements
    const deadlinesItemsContainer = document.getElementById('deadlines-items-container');
    const deadlinesCountBadge = document.getElementById('deadlines-count-badge');

    // Bottom Action Button
    const btnPrimaryAction = document.getElementById('btn-primary-action');
    const btnPrimaryActionText = document.getElementById('btn-primary-action-text');
    const toastEl = document.getElementById('toast');

    // Toast Helper
    function showToast(text, duration = 2500) {
        if (!toastEl) return;
        toastEl.textContent = text;
        toastEl.classList.remove('hidden');
        setTimeout(() => {
            toastEl.classList.add('hidden');
        }, duration);
    }

    // 1. Ініціалізація заголовку
    if (userGreetingEl) {
        userGreetingEl.textContent = `Привіт, ${currentUser.firstName}! ✨`;
    }

    // Кнопка закриття
    if (btnCloseApp) {
        btnCloseApp.addEventListener('click', () => {
            if (tg) {
                tg.close();
            } else {
                showToast("Закриття додатку");
            }
        });
    }

    // Кнопка оновлення (три крапки / sync)
    if (btnSync) {
        btnSync.addEventListener('click', async () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
            showToast("🔄 Оновлюю дані...");
            await refreshAllData();
            showToast("✅ Дані успішно оновлено!");
        });
    }

    // Клік по стікеру кави
    if (btnAvatarBadge) {
        btnAvatarBadge.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            showToast(`☕ Гарного дня, ${currentUser.firstName}! Група ІП-66`);
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

    // Клік по бузковій картці пари
    if (featuredCard) {
        featuredCard.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            const activeLink = featuredCard.getAttribute('data-link');
            if (activeLink) {
                window.open(activeLink, '_blank');
            } else {
                switchToTab('tab-schedule');
            }
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

        tabContents.forEach(c => {
            if (c.id === targetTab) {
                c.classList.add('active');
            } else {
                c.classList.remove('active');
            }
        });

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
        });
    });

    // 4. Оновлення нижньої кнопки дії
    function updateBottomButtonState() {
        if (!btnPrimaryAction || !btnPrimaryActionText) return;

        if (currentTab === 'tab-queue') {
            const myItem = currentQueue.find(item => item.user_id === currentUser.id);
            if (myItem) {
                const myIdx = currentQueue.indexOf(myItem) + 1;
                btnPrimaryActionText.textContent = `✅ Ви у черзі #${myIdx} (${activeSubject})`;
                btnPrimaryAction.disabled = false;
            } else {
                const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
                if (sorted.length === 0) {
                    btnPrimaryActionText.textContent = `✋ Зайняти чергу ${activeSubject} (оберіть лабу)`;
                    btnPrimaryAction.disabled = false; // Клік підкаже обрати
                } else {
                    const labsText = sorted.length === 1 ? `Лаба ${sorted[0]}` : `Лаби ${sorted.join(', ')}`;
                    btnPrimaryActionText.textContent = `🚀 Зайняти чергу: ${labsText}`;
                    btnPrimaryAction.disabled = false;
                }
            }
        } else if (currentTab === 'tab-schedule') {
            const firstWithLink = scheduleLessons.find(l => l.link_url);
            if (firstWithLink) {
                btnPrimaryActionText.textContent = `🔗 Приєднатися: ${firstWithLink.name.substring(0, 24)}...`;
            } else {
                btnPrimaryActionText.textContent = `📅 Розклад ІП-66`;
            }
            btnPrimaryAction.disabled = false;
        } else if (currentTab === 'tab-deadlines') {
            btnPrimaryActionText.textContent = `🔄 Оновити дедлайни з Classroom`;
            btnPrimaryAction.disabled = false;
        }
    }

    // Обробник кліку на головну кнопку
    if (btnPrimaryAction) {
        btnPrimaryAction.addEventListener('click', async () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');

            if (currentTab === 'tab-queue') {
                const myItem = currentQueue.find(item => item.user_id === currentUser.id);
                if (myItem) {
                    showToast(`Ви вже у черзі ${activeSubject} на позиції #${currentQueue.indexOf(myItem) + 1}!`);
                    return;
                }

                const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
                if (sorted.length === 0) {
                    showToast("⚠️ Будь ласка, оберіть хоча б одну лабу в сітці 1..9!");
                    if (labsGridEl) labsGridEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    return;
                }
                await submitJoinQueue();
            } else if (currentTab === 'tab-schedule') {
                const firstWithLink = scheduleLessons.find(l => l.link_url);
                if (firstWithLink) {
                    window.open(firstWithLink.link_url, '_blank');
                } else {
                    showToast("У розкладі немає збережених Zoom/Meet посилань");
                }
            } else if (currentTab === 'tab-deadlines') {
                await fetchDeadlines();
                showToast("Дедлайни оновлено!");
            }
        });
    }

    // 5. Логіка черги: вибір лаб 1..9
    function renderLabsGrid() {
        if (!labsGridEl) return;
        labsGridEl.innerHTML = '';
        for (let i = 1; i <= 9; i++) {
            const btn = document.createElement('button');
            const isSelected = selectedLabs.has(i);
            btn.className = `lab-pill-btn ${isSelected ? 'selected' : ''}`;
            btn.innerHTML = `<span>${isSelected ? '✅' : '▫️'}</span><span>Лаба ${i}</span>`;
            btn.addEventListener('click', () => toggleLab(i));
            labsGridEl.appendChild(btn);
        }
    }

    function toggleLab(num) {
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
        if (previewTextEl) {
            previewTextEl.textContent = `🎯 Обрано: ${labsText} • ⭐ Пріоритет: Лаба ${minLab} (найстаріша)`;
        }
        if (priorityPreviewEl) priorityPreviewEl.classList.remove('hidden');
    }

    // Перемикач ОП / АСД
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
        selectedLabs.clear();
        renderLabsGrid();
        updatePriorityPreview();
        updateBottomButtonState();
        fetchQueue();
    }

    if (subjTabOp) subjTabOp.addEventListener('click', () => switchQueueSubject('ОП'));
    if (subjTabAsd) subjTabAsd.addEventListener('click', () => switchQueueSubject('АСД'));

    // Отримання черги
    async function fetchQueue() {
        try {
            // Отримуємо поточну активну чергу
            const res = await fetch(`/api/queue?subject=${encodeURIComponent(activeSubject)}&chat_id=${chatId}`);
            const data = await res.json();
            if (!data.success) return;

            currentQueue = data.items || [];
            allQueuesData[activeSubject] = currentQueue;
            renderQueueList(currentQueue);

            // Оновлюємо бейджі
            if (activeSubject === 'ОП') {
                if (badgeOpCount) badgeOpCount.textContent = currentQueue.length;
                if (miniOpStat) miniOpStat.textContent = `${currentQueue.length}`;
                if (miniOpSub) miniOpSub.textContent = currentQueue.length > 0 ? `Активна черга 🔥` : `Черга вільна`;
            } else {
                if (badgeAsdCount) badgeAsdCount.textContent = currentQueue.length;
                if (miniAsdStat) miniAsdStat.textContent = `${currentQueue.length}`;
                if (miniAsdSub) miniAsdSub.textContent = currentQueue.length > 0 ? `Активна черга 🔥` : `Черга вільна`;
            }

            // Також оновлюємо іншу чергу у фоні для міні-картки
            const otherSubj = activeSubject === 'ОП' ? 'АСД' : 'ОП';
            fetchOtherQueueCount(otherSubj);

            // Статус користувача в черзі
            const meIndex = currentQueue.findIndex(item => item.user_id === currentUser.id);
            if (meIndex !== -1) {
                const me = currentQueue[meIndex];
                if (myStatusBox) myStatusBox.classList.remove('hidden');
                if (myPosText) myPosText.textContent = `Ви #${meIndex + 1} у черзі (${activeSubject})!`;
                if (myLabsText) myLabsText.textContent = `${me.lab_number || 'Лаба не вказана'} • ⭐ Пріоритет: Лаба ${me.lab_priority || 1}`;
            } else {
                if (myStatusBox) myStatusBox.classList.add('hidden');
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
            const isMe = item.user_id === currentUser.id;
            const rank = idx + 1;
            const isGold = rank === 1;
            const rankClass = isGold ? 'gold' : '';
            const labBadge = item.lab_number ? `<span class="queue-lab-tag">${escapeHtml(item.lab_number)}</span>` : '';

            return `
                <div class="queue-person-card ${isMe ? 'is-me' : ''}">
                    <div class="queue-rank-badge ${rankClass}">#${rank}</div>
                    <div class="queue-name-col">
                        <span class="queue-name">${escapeHtml(item.user_name)}${isMe ? ' (Ви)' : ''}</span>
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

        const labLabel = sorted.length === 1 ? `Лаба ${sorted[0]}` : `Лаби ${sorted.join(', ')}`;
        try {
            const res = await fetch('/api/queue/join', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chat_id: chatId,
                    subject: activeSubject,
                    user_id: currentUser.id,
                    user_name: currentUser.name,
                    username: currentUser.username,
                    lab_number: labLabel
                })
            });
            const data = await res.json();
            if (data.success) {
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                showToast(`✅ Ви успішно стали у чергу ${activeSubject}!`);
                await fetchQueue();
            } else {
                showToast(data.message || 'Помилка запису');
            }
        } catch (err) {
            showToast('Помилка з\'єднання з сервером');
        }
    }

    // Вихід з черги
    if (btnLeaveQueue) {
        btnLeaveQueue.addEventListener('click', async () => {
            if (!confirm(`Ви дійсно бажаєте вийти з черги ${activeSubject}?`)) return;
            try {
                const res = await fetch('/api/queue/leave', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        chat_id: chatId,
                        subject: activeSubject,
                        user_id: currentUser.id
                    })
                });
                const data = await res.json();
                if (data.success) {
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

    // 6. Розклад пар (реальні дані)
    if (btnDayToday) {
        btnDayToday.addEventListener('click', () => {
            scheduleDay = 'today';
            btnDayToday.style.background = '#F3E8FF';
            btnDayToday.style.color = '#6D28D9';
            btnDayTomorrow.style.background = '#F1F5F9';
            btnDayTomorrow.style.color = '#64748B';
            if (scheduleDayTitle) scheduleDayTitle.textContent = 'Розклад на сьогодні';
            fetchSchedule('today');
        });
    }

    if (btnDayTomorrow) {
        btnDayTomorrow.addEventListener('click', () => {
            scheduleDay = 'tomorrow';
            btnDayTomorrow.style.background = '#F3E8FF';
            btnDayTomorrow.style.color = '#6D28D9';
            btnDayToday.style.background = '#F1F5F9';
            btnDayToday.style.color = '#64748B';
            if (scheduleDayTitle) scheduleDayTitle.textContent = 'Розклад на завтра';
            fetchSchedule('tomorrow');
        });
    }

    async function fetchSchedule(day) {
        if (scheduleLoading) scheduleLoading.classList.remove('hidden');
        if (scheduleItemsContainer) scheduleItemsContainer.innerHTML = '';

        try {
            const res = await fetch(`/api/schedule?day=${day}`);
            const data = await res.json();
            if (scheduleLoading) scheduleLoading.classList.add('hidden');

            if (!data.success || !data.lessons || data.lessons.length === 0) {
                if (scheduleItemsContainer) {
                    scheduleItemsContainer.innerHTML = '<div style="text-align:center; padding:24px 0; color:var(--text-muted); font-size:14px;">🎉 У цей день пар немає! Відпочивайте.</div>';
                }
                if (day === 'today') {
                    updateFeaturedCardNoLessons();
                }
                return;
            }

            scheduleLessons = data.lessons;

            // Оновлюємо бузкову картку на основі реального часу
            if (day === 'today') {
                updateFeaturedCardWithLessons(data.lessons);
            }

            if (scheduleItemsContainer) {
                scheduleItemsContainer.innerHTML = data.lessons.map(l => {
                    const linkBtn = l.link_url
                        ? `<a href="${l.link_url}" target="_blank" style="color:#7C3AED; font-weight:700; text-decoration:none; font-size:13px; background:#F3E8FF; padding:4px 10px; border-radius:99px;">🔗 Приєднатися</a>`
                        : `<span style="color:var(--text-muted); font-size:12px;">Без лінка</span>`;

                    return `
                        <div class="task-item-card">
                            <div class="task-meta-block">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                    <span style="font-size:12.5px; font-weight:700; color:#7C3AED;">Пара ${l.pair_number || 1} • ${l.time || '10:15'} (${l.type || 'Пара'})</span>
                                    ${linkBtn}
                                </div>
                                <span class="task-title">${escapeHtml(l.name)}</span>
                                <span class="task-due-date">👤 ${escapeHtml(l.lecturer || 'Викладач не вказаний')}</span>
                            </div>
                        </div>
                    `;
                }).join('');
            }
            updateHeroSubtitle();
        } catch (err) {
            if (scheduleLoading) scheduleLoading.classList.add('hidden');
        }
    }

    // Динамічний розрахунок статусу поточної пари
    function updateFeaturedCardWithLessons(lessons) {
        if (!featuredCard) return;

        // Поточний час у Києві
        const now = new Date();
        const curMinutes = now.getHours() * 60 + now.getMinutes();

        // Розклад дзвінків КПІ:
        // 1 пара: 08:30 - 10:05 (510 - 605)
        // 2 пара: 10:25 - 12:00 (625 - 720)
        // 3 пара: 12:20 - 13:55 (740 - 835)
        // 4 пара: 14:15 - 15:50 (855 - 950)
        // 5 пара: 16:10 - 17:45 (970 - 1065)
        let currentLesson = null;
        let nextLesson = null;

        for (const l of lessons) {
            const timeStr = l.time || '';
            const parts = timeStr.split(':');
            if (parts.length >= 2) {
                const startM = parseInt(parts[0]) * 60 + parseInt(parts[1]);
                const endM = startM + 95; // 1 пара = 1 год 35 хв
                if (curMinutes >= startM && curMinutes <= endM) {
                    currentLesson = l;
                    break;
                } else if (curMinutes < startM && !nextLesson) {
                    nextLesson = l;
                }
            }
        }

        if (currentLesson) {
            if (featuredStatusTag) featuredStatusTag.textContent = '🔴 Зараз триває пара';
            if (featuredTimePill) featuredTimePill.textContent = currentLesson.time || 'Триває';
            if (featuredCardTitle) featuredCardTitle.textContent = currentLesson.name;
            if (featuredCardMeta) featuredCardMeta.textContent = `${currentLesson.type || 'Пара'} • ${currentLesson.lecturer || 'КПІ'}`;
            if (currentLesson.link_url) {
                featuredCard.setAttribute('data-link', currentLesson.link_url);
            }
        } else if (nextLesson) {
            if (featuredStatusTag) featuredStatusTag.textContent = '⏳ Наступна пара';
            if (featuredTimePill) featuredTimePill.textContent = nextLesson.time || 'Сьогодні';
            if (featuredCardTitle) featuredCardTitle.textContent = nextLesson.name;
            if (featuredCardMeta) featuredCardMeta.textContent = `${nextLesson.type || 'Пара'} • ${nextLesson.lecturer || 'КПІ'}`;
            if (nextLesson.link_url) {
                featuredCard.setAttribute('data-link', nextLesson.link_url);
            }
        } else {
            // Пари на сьогодні завершено
            if (featuredStatusTag) featuredStatusTag.textContent = '✨ Пари на сьогодні завершено';
            if (featuredTimePill) featuredTimePill.textContent = 'Відпочинок';
            if (featuredCardTitle) featuredCardTitle.textContent = 'Всі заняття на сьогодні пройшли!';
            if (featuredCardMeta) featuredCardMeta.textContent = 'Перевірте розклад на завтра або здайте лабу в черзі 🎯';
            featuredCard.removeAttribute('data-link');
        }
    }

    function updateFeaturedCardNoLessons() {
        if (!featuredCard) return;
        if (featuredStatusTag) featuredStatusTag.textContent = '🎉 Вихідний / Пар немає';
        if (featuredTimePill) featuredTimePill.textContent = 'Вільний день';
        if (featuredCardTitle) featuredCardTitle.textContent = 'Сьогодні пар немає';
        if (featuredCardMeta) featuredCardMeta.textContent = 'Відпочивайте або готуйтеся до лабораторних робіт!';
        featuredCard.removeAttribute('data-link');
    }

    // 7. Справжні дедлайни з Classroom
    let deadlinesCache = [];

    async function fetchDeadlines() {
        if (!deadlinesItemsContainer) return;
        try {
            const res = await fetch('/api/deadlines');
            const data = await res.json();
            if (!data.success || !data.deadlines || data.deadlines.length === 0) {
                deadlinesItemsContainer.innerHTML = '<div style="text-align:center; padding:24px 0; color:var(--text-muted); font-size:14px;">✅ Всі дедлайни закриті! Нових завдань немає.</div>';
                if (deadlinesCountBadge) deadlinesCountBadge.textContent = '0';
                return;
            }

            deadlinesCache = data.deadlines;
            if (deadlinesCountBadge) deadlinesCountBadge.textContent = data.total || deadlinesCache.length;

            deadlinesItemsContainer.innerHTML = deadlinesCache.map(d => {
                const linkAttr = d.alternate_link ? `data-link="${escapeHtml(d.alternate_link)}"` : '';
                const dueText = d.due_time ? `⏰ Дедлайн: ${d.due_time.substring(0, 16)}` : 'Без дедлайну';
                const summaryText = d.ai_summary ? `<div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">💡 ${escapeHtml(d.ai_summary)}</div>` : '';

                return `
                    <div class="task-item-card" ${linkAttr} style="cursor:pointer;">
                        <div class="custom-checkbox">
                            <svg viewBox="0 0 24 24" fill="none">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                        </div>
                        <div class="task-meta-block">
                            <span class="task-due-date" style="color:#7C3AED; font-weight:700;">${escapeHtml(d.course_name || 'Курс')}</span>
                            <span class="task-title" style="margin:2px 0;">${escapeHtml(d.title)}</span>
                            <span class="task-due-date">${escapeHtml(dueText)}</span>
                            ${summaryText}
                        </div>
                    </div>
                `;
            }).join('');

            // Клік по чекбоксу відмічає виконання
            deadlinesItemsContainer.querySelectorAll('.task-item-card').forEach(el => {
                const checkbox = el.querySelector('.custom-checkbox');
                if (checkbox) {
                    checkbox.addEventListener('click', (e) => {
                        e.stopPropagation();
                        el.classList.toggle('is-checked');
                        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
                    });
                }
                el.addEventListener('click', () => {
                    const link = el.getAttribute('data-link');
                    if (link) window.open(link, '_blank');
                });
            });

            updateHeroSubtitle();
        } catch (err) {
            deadlinesItemsContainer.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-muted);">Не вдалося завантажити дедлайни</div>';
        }
    }

    function updateHeroSubtitle() {
        if (!heroSubtitleEl) return;
        const opCount = (allQueuesData['ОП'] || []).length;
        const asdCount = (allQueuesData['АСД'] || []).length;
        const totalQueued = opCount + asdCount;
        const totalLessons = scheduleLessons.length;
        const totalDeadlines = deadlinesCache.length;

        heroSubtitleEl.textContent = `У чергах: ${totalQueued} студентів • Пар сьогодні: ${totalLessons} • Дедлайнів: ${totalDeadlines}`;
    }

    async function refreshAllData() {
        await Promise.all([
            fetchQueue(),
            fetchSchedule(scheduleDay),
            fetchDeadlines()
        ]);
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Первинний запуск
    renderLabsGrid();
    updatePriorityPreview();
    updateBottomButtonState();
    refreshAllData();

    // Автоматичне фонове оновлення черги кожні 4 секунди
    pollInterval = setInterval(() => {
        if (currentTab === 'tab-queue') {
            fetchQueue();
        }
    }, 4000);
});
