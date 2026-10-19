// --- Telegram Mini App Frontend Controller (Pastel Campus Edition) ---
document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
        tg.ready();
        tg.expand();
    }

    // Extract user info from Telegram WebApp SDK or fallback for preview
    const tgUser = tg?.initDataUnsafe?.user;
    const currentUser = {
        id: tgUser?.id || 999001,
        name: tgUser ? [tgUser.first_name, tgUser.last_name].filter(Boolean).join(' ') : 'Саша',
        firstName: tgUser?.first_name || 'Саша',
        username: tgUser?.username || 'student'
    };

    // Extract query params (chat_id, subject) passed by bot
    const urlParams = new URLSearchParams(window.location.search);
    const chatId = parseInt(urlParams.get('chat_id')) || 0;
    const initialSubject = (urlParams.get('subject') || 'ОП').toUpperCase();

    // App State
    let activeSubject = ['ОП', 'АСД'].includes(initialSubject) ? initialSubject : 'ОП';
    let selectedLabs = new Set();
    let currentQueue = [];
    let scheduleDay = 'today';
    let currentTab = 'tab-overview';
    let pollInterval = null;

    // DOM Elements
    const btnCloseApp = document.getElementById('btn-close-app');
    const userGreetingEl = document.getElementById('user-greeting');
    const heroSubtitleEl = document.getElementById('hero-subtitle');
    const btnSync = document.getElementById('btn-sync');
    const featuredCard = document.getElementById('featured-card');
    const featuredStatusTag = document.getElementById('featured-status-tag');
    const featuredTimePill = document.getElementById('featured-time-pill');
    const featuredCardTitle = document.getElementById('featured-card-title');
    const featuredCardMeta = document.getElementById('featured-card-meta');

    const miniCardLeft = document.getElementById('mini-card-left');
    const miniCardRight = document.getElementById('mini-card-right');

    const segButtons = document.querySelectorAll('.seg-pill-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const overviewTasksList = document.getElementById('overview-tasks-list');

    const btnPrimaryAction = document.getElementById('btn-primary-action');
    const btnPrimaryActionText = document.getElementById('btn-primary-action-text');

    // Queue Elements
    const subjPills = document.querySelectorAll('.subj-pill-tab');
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
    const badgeOpCount = document.getElementById('badge-op-count');
    const badgeAsdCount = document.getElementById('badge-asd-count');

    // Schedule Elements
    const btnDayToday = document.getElementById('btn-day-today');
    const btnDayTomorrow = document.getElementById('btn-day-tomorrow');
    const scheduleItemsContainer = document.getElementById('schedule-items-container');
    const scheduleLoading = document.getElementById('schedule-loading');

    // 1. Setup Header & Hero Greeting
    if (userGreetingEl) {
        userGreetingEl.textContent = `Привет, ${currentUser.firstName}! ✨`;
    }

    if (btnCloseApp) {
        btnCloseApp.addEventListener('click', () => {
            if (tg) tg.close();
        });
    }

    // 2. Default Tasks Mock (Exact match to screenshot reference)
    let tasksState = [
        { id: 't1', title: 'Лабораторная №3 по АСД', date: 'Сегодня, 23:59', checked: false },
        { id: 't2', title: 'Расчётка по высшей математике', date: 'Завтра, 14:00', checked: true },
        { id: 't3', title: 'Конспект по Базам Данных (Лекция 5)', date: '24 октября', checked: false }
    ];

    function renderTasksList() {
        if (!overviewTasksList) return;
        overviewTasksList.innerHTML = tasksState.map(t => `
            <div class="task-item-card ${t.checked ? 'is-checked' : ''}" data-task-id="${t.id}">
                <div class="custom-checkbox">
                    <svg viewBox="0 0 24 24" fill="none">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                </div>
                <div class="task-meta-block">
                    <span class="task-title">${escapeHtml(t.title)}</span>
                    <span class="task-due-date">${escapeHtml(t.date)}</span>
                </div>
            </div>
        `).join('');

        // Add toggle listeners
        overviewTasksList.querySelectorAll('.task-item-card').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.getAttribute('data-task-id');
                const task = tasksState.find(item => item.id === id);
                if (task) {
                    task.checked = !task.checked;
                    if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
                    renderTasksList();
                }
            });
        });
    }

    // 3. Tab Navigation
    segButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            currentTab = targetTab;
            segButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const targetEl = document.getElementById(targetTab);
            if (targetEl) targetEl.classList.add('active');

            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');

            updateBottomButtonState();

            if (targetTab === 'tab-queue') fetchQueue();
            if (targetTab === 'tab-schedule') fetchSchedule(scheduleDay);
            if (targetTab === 'tab-overview') renderTasksList();
        });
    });

    function updateBottomButtonState() {
        if (!btnPrimaryAction || !btnPrimaryActionText) return;

        if (currentTab === 'tab-overview') {
            btnPrimaryActionText.textContent = '🌱 Отметиться на занятии';
            btnPrimaryAction.disabled = false;
        } else if (currentTab === 'tab-queue') {
            const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
            if (sorted.length === 0) {
                btnPrimaryActionText.textContent = '✋ Зайняти чергу (оберіть лабу)';
                btnPrimaryAction.disabled = true;
            } else {
                const labsText = sorted.length === 1 ? `Лаба ${sorted[0]}` : `Лаби ${sorted.join(', ')}`;
                btnPrimaryActionText.textContent = `🚀 Зайняти: ${labsText}`;
                btnPrimaryAction.disabled = false;
            }
        } else if (currentTab === 'tab-schedule') {
            btnPrimaryActionText.textContent = '🔗 Відкрити пару в Zoom';
            btnPrimaryAction.disabled = false;
        }
    }

    // Bottom Action Click Handler
    if (btnPrimaryAction) {
        btnPrimaryAction.addEventListener('click', async () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');

            if (currentTab === 'tab-overview') {
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                alert('✅ Вы успешно отметились на занятии!');
            } else if (currentTab === 'tab-queue') {
                await submitJoinQueue();
            } else if (currentTab === 'tab-schedule') {
                const firstLessonLink = document.querySelector('.lesson-join-link');
                if (firstLessonLink && firstLessonLink.href) {
                    window.open(firstLessonLink.href, '_blank');
                } else {
                    alert('Зараз немає активного посилання на пару');
                }
            }
        });
    }

    // Mini cards click handlers
    if (miniCardLeft) {
        miniCardLeft.addEventListener('click', () => {
            const queueBtn = document.querySelector('[data-tab="tab-queue"]');
            if (queueBtn) queueBtn.click();
        });
    }
    if (miniCardRight) {
        miniCardRight.addEventListener('click', () => {
            const schedBtn = document.querySelector('[data-tab="tab-schedule"]');
            if (schedBtn) schedBtn.click();
        });
    }

    // 4. Queue Logic: Multi-Select Labs Grid (1..9)
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

    // Subject Switcher in Queue Tab
    subjPills.forEach(btn => {
        btn.addEventListener('click', () => {
            const subj = btn.getAttribute('data-subject');
            if (subj === activeSubject) return;

            activeSubject = subj;
            subjPills.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            selectedLabs.clear();
            renderLabsGrid();
            updatePriorityPreview();
            updateBottomButtonState();
            fetchQueue();

            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
        });
    });

    // Fetch & Render Live Queue
    async function fetchQueue() {
        try {
            const res = await fetch(`/api/queue?subject=${encodeURIComponent(activeSubject)}&chat_id=${chatId}`);
            const data = await res.json();
            if (!data.success) return;

            currentQueue = data.items || [];
            renderQueueList(currentQueue);

            if (activeSubject === 'ОП' && badgeOpCount) badgeOpCount.textContent = currentQueue.length;
            if (activeSubject === 'АСД' && badgeAsdCount) badgeAsdCount.textContent = currentQueue.length;

            // My Status Card
            const meIndex = currentQueue.findIndex(item => item.user_id === currentUser.id);
            if (meIndex !== -1) {
                const me = currentQueue[meIndex];
                if (myStatusBox) myStatusBox.classList.remove('hidden');
                if (myPosText) myPosText.textContent = `Ви #${meIndex + 1} у черзі (${activeSubject})!`;
                if (myLabsText) myLabsText.textContent = `${me.lab_number || 'Лаба не вказана'} • ⭐ Пріоритет: Лаба ${me.lab_priority || 1}`;
            } else {
                if (myStatusBox) myStatusBox.classList.add('hidden');
            }
        } catch (err) {
            console.error('Queue fetch error:', err);
        }
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

    // Submit Join Queue
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
                await fetchQueue();
                updateBottomButtonState();
            } else {
                alert(data.message || 'Помилка');
            }
        } catch (err) {
            console.error('Join error:', err);
        }
    }

    // Leave Queue
    if (btnLeaveQueue) {
        btnLeaveQueue.addEventListener('click', async () => {
            if (!confirm(`Вийти з черги ${activeSubject}?`)) return;
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
                    await fetchQueue();
                }
            } catch (err) {
                console.error('Leave error:', err);
            }
        });
    }

    // Next Student
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
                        alert(`🎯 Наступний: ${data.student.user_name} (${data.student.lab_number})`);
                    } else {
                        alert('Черга порожня!');
                    }
                    await fetchQueue();
                }
            } catch (err) {
                console.error('Next error:', err);
            }
        });
    }

    // 5. Schedule Logic
    if (btnDayToday) {
        btnDayToday.addEventListener('click', () => {
            scheduleDay = 'today';
            btnDayToday.style.background = '#F3E8FF';
            btnDayToday.style.color = '#6D28D9';
            btnDayTomorrow.style.background = '#F1F5F9';
            btnDayTomorrow.style.color = '#64748B';
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
                    scheduleItemsContainer.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-muted);">🎉 У цей день пар немає! Відпочивайте.</div>';
                }
                return;
            }

            // Also update featured card with today's first lesson if on today
            if (day === 'today' && data.lessons.length > 0) {
                const first = data.lessons[0];
                if (featuredCardTitle) featuredCardTitle.textContent = first.name || 'Алгоритми та структури даних';
                if (featuredTimePill) featuredTimePill.textContent = first.time ? `${first.time}` : '10:15 - 11:45';
                if (featuredCardMeta) featuredCardMeta.textContent = `${first.type || 'Пара'} • ${first.lecturer || 'Викладач'}`;
            }

            if (scheduleItemsContainer) {
                scheduleItemsContainer.innerHTML = data.lessons.map(l => {
                    const linkBtn = l.link_url
                        ? `<a href="${l.link_url}" target="_blank" class="lesson-join-link" style="color:#7C3AED; font-weight:700; text-decoration:none; font-size:13px;">🔗 Приєднатися</a>`
                        : `<span style="color:var(--text-muted); font-size:12px;">Без посилання</span>`;

                    return `
                        <div class="task-item-card">
                            <div class="task-meta-block">
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <span style="font-size:12px; font-weight:700; color:#7C3AED;">${l.time || '10:15'} (${l.type || 'Пара'})</span>
                                    ${linkBtn}
                                </div>
                                <span class="task-title" style="margin-top:4px;">${escapeHtml(l.name)}</span>
                                <span class="task-due-date">👤 ${escapeHtml(l.lecturer || 'Викладач не вказаний')}</span>
                            </div>
                        </div>
                    `;
                }).join('');
            }
        } catch (err) {
            if (scheduleLoading) scheduleLoading.classList.add('hidden');
            if (scheduleItemsContainer) {
                scheduleItemsContainer.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-muted);">Не вдалося завантажити розклад</div>';
            }
        }
    }

    // Sync button
    if (btnSync) {
        btnSync.addEventListener('click', () => {
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            fetchQueue();
            fetchSchedule(scheduleDay);
            renderTasksList();
        });
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Initialize UI
    renderTasksList();
    renderLabsGrid();
    updatePriorityPreview();
    updateBottomButtonState();
    fetchQueue();
    fetchSchedule('today');

    // Auto-polling for live queue every 4 seconds
    pollInterval = setInterval(() => {
        if (currentTab === 'tab-queue') fetchQueue();
    }, 4000);
});
