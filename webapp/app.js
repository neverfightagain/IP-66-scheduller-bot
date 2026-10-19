// --- Telegram Mini App Frontend Controller ---
document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
        tg.ready();
        tg.expand();
    }

    // Extract user info from Telegram WebApp SDK or fallback for desktop/browser preview
    const tgUser = tg?.initDataUnsafe?.user;
    const currentUser = {
        id: tgUser?.id || 999001,
        name: tgUser ? [tgUser.first_name, tgUser.last_name].filter(Boolean).join(' ') : 'Студент ІП-66',
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
    let pollInterval = null;

    // DOM Elements
    const userAvatarEl = document.getElementById('user-avatar');
    const userGreetingEl = document.getElementById('user-greeting');
    const labsGridEl = document.getElementById('labs-grid');
    const priorityPreviewEl = document.getElementById('priority-preview');
    const previewTextEl = document.getElementById('preview-text');
    const btnSubmitQueue = document.getElementById('btn-submit-queue');
    const queueItemsContainer = document.getElementById('queue-items-container');
    const queueEmptyEl = document.getElementById('queue-empty');
    const myStatusCard = document.getElementById('my-status-card');
    const myPosBadge = document.getElementById('my-pos-badge');
    const myLabsLabel = document.getElementById('my-labs-label');
    const myPrioLabel = document.getElementById('my-prio-label');
    const btnLeaveQueue = document.getElementById('btn-leave-queue');
    const btnNextStudent = document.getElementById('btn-next-student');
    const btnSync = document.getElementById('btn-sync');
    const badgeOpCount = document.getElementById('badge-op-count');
    const badgeAsdCount = document.getElementById('badge-asd-count');

    // Setup Header User Profile
    if (userGreetingEl) userGreetingEl.textContent = `Привіт, ${currentUser.name.split(' ')[0]}!`;
    if (userAvatarEl) {
        userAvatarEl.textContent = currentUser.name.charAt(0).toUpperCase();
        if (tgUser?.photo_url) {
            userAvatarEl.style.backgroundImage = `url(${tgUser.photo_url})`;
            userAvatarEl.style.backgroundSize = 'cover';
            userAvatarEl.textContent = '';
        }
    }

    // --- Tab Navigation ---
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');
            navItems.forEach(n => n.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            item.classList.add('active');
            const targetEl = document.getElementById(targetTab);
            if (targetEl) targetEl.classList.add('active');

            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');

            if (targetTab === 'tab-schedule') fetchSchedule(scheduleDay);
            if (targetTab === 'tab-deadlines') fetchDeadlines();
            if (targetTab === 'tab-queue') fetchQueue();
        });
    });

    // --- Subject Switcher (ОП / АСД) ---
    const subjButtons = document.querySelectorAll('.subj-btn');
    subjButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const subj = btn.getAttribute('data-subject');
            if (subj === activeSubject) return;

            activeSubject = subj;
            subjButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            selectedLabs.clear();
            renderLabsGrid();
            updatePriorityPreview();
            fetchQueue();

            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
        });
    });

    // --- Multi-Select Labs Grid (1..9) ---
    function renderLabsGrid() {
        labsGridEl.innerHTML = '';
        for (let i = 1; i <= 9; i++) {
            const btn = document.createElement('button');
            const isSelected = selectedLabs.has(i);
            btn.className = `lab-btn ${isSelected ? 'selected' : ''}`;
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
    }

    function updatePriorityPreview() {
        const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
        if (sorted.length === 0) {
            priorityPreviewEl.classList.add('hidden');
            btnSubmitQueue.disabled = true;
            btnSubmitQueue.innerHTML = '<span>✋ Зайняти чергу</span>';
            return;
        }

        const minLab = sorted[0];
        const labsText = sorted.length === 1 ? `Лаба ${minLab}` : `Лаби ${sorted.join(', ')}`;
        previewTextEl.textContent = `🎯 Обрано: ${labsText} • ⭐ Пріоритет: Лаба ${minLab} (найстаріша)`;
        priorityPreviewEl.classList.remove('hidden');

        btnSubmitQueue.disabled = false;
        btnSubmitQueue.innerHTML = `<span>🚀 Зайняти чергу: ${labsText}</span>`;
    }

    // --- Fetch & Render Live Queue ---
    async function fetchQueue() {
        try {
            const res = await fetch(`/api/queue?subject=${encodeURIComponent(activeSubject)}&chat_id=${chatId}`);
            const data = await res.json();
            if (!data.success) return;

            currentQueue = data.items || [];
            renderQueueList(currentQueue);

            // Update subject badge count
            if (activeSubject === 'ОП' && badgeOpCount) badgeOpCount.textContent = currentQueue.length;
            if (activeSubject === 'АСД' && badgeAsdCount) badgeAsdCount.textContent = currentQueue.length;

            // Check if current user is in queue
            const meIndex = currentQueue.findIndex(item => item.user_id === currentUser.id);
            if (meIndex !== -1) {
                const me = currentQueue[meIndex];
                myStatusCard.classList.remove('hidden');
                myPosBadge.textContent = `#${meIndex + 1}`;
                myLabsLabel.textContent = me.lab_number || 'Лаба не вказана';
                myPrioLabel.textContent = `⭐ Пріоритет: Лаба ${me.lab_priority || 1}`;

                // Pre-fill user's defended labs if not modified yet
                if (selectedLabs.size === 0 && me.lab_number) {
                    const matches = me.lab_number.match(/\d+/g);
                    if (matches) {
                        matches.forEach(m => selectedLabs.add(parseInt(m)));
                        renderLabsGrid();
                        updatePriorityPreview();
                    }
                }
            } else {
                myStatusCard.classList.add('hidden');
            }
        } catch (err) {
            console.error('Queue fetch error:', err);
        }
    }

    function renderQueueList(items) {
        if (!items || items.length === 0) {
            queueItemsContainer.innerHTML = '';
            queueEmptyEl.classList.remove('hidden');
            return;
        }

        queueEmptyEl.classList.add('hidden');
        queueItemsContainer.innerHTML = items.map((item, idx) => {
            const isMe = item.user_id === currentUser.id;
            const rank = idx + 1;
            const medal = rank === 1 ? '🥇' : (rank === 2 ? '🥈' : (rank === 3 ? '🥉' : `#${rank}`));
            const medalClass = rank === 1 ? 'gold' : '';
            const initial = (item.user_name || 'С').charAt(0).toUpperCase();
            const usernameStr = item.username ? `@${item.username}` : '';
            const labBadge = item.lab_number ? `<span class="queue-lab-badge">${item.lab_number}</span>` : '';

            return `
                <div class="queue-item ${isMe ? 'is-me' : ''}">
                    <div class="queue-rank ${medalClass}">${medal}</div>
                    <div class="queue-avatar">${initial}</div>
                    <div class="queue-user-meta">
                        <span class="queue-user-name">${escapeHtml(item.user_name)}${isMe ? ' (Ви)' : ''}</span>
                        <span class="queue-user-handle">${escapeHtml(usernameStr)}</span>
                    </div>
                    ${labBadge}
                </div>
            `;
        }).join('');
    }

    // --- Queue Actions ---
    btnSubmitQueue.addEventListener('click', async () => {
        const sorted = Array.from(selectedLabs).sort((a, b) => a - b);
        if (sorted.length === 0) return;

        const labLabel = sorted.length === 1 ? `Лаба ${sorted[0]}` : `Лаби ${sorted.join(', ')}`;
        btnSubmitQueue.disabled = true;

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
            } else {
                alert(data.message || 'Помилка запису');
            }
        } catch (err) {
            console.error('Join error:', err);
        } finally {
            btnSubmitQueue.disabled = false;
        }
    });

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
                if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('warning');
                await fetchQueue();
            }
        } catch (err) {
            console.error('Leave error:', err);
        }
    });

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
                    alert(`🎯 Наступний на захист: ${data.student.user_name} (${data.student.lab_number})`);
                } else {
                    alert('Черга порожня!');
                }
                await fetchQueue();
            }
        } catch (err) {
            console.error('Next error:', err);
        }
    });

    btnSync.addEventListener('click', () => {
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
        fetchQueue();
    });

    // --- Schedule Tab Logic ---
    const scheduleToggleBtns = document.querySelectorAll('.toggle-btn');
    scheduleToggleBtns.forEach(b => {
        b.addEventListener('click', () => {
            scheduleToggleBtns.forEach(btn => btn.classList.remove('active'));
            b.classList.add('active');
            scheduleDay = b.getAttribute('data-day');
            fetchSchedule(scheduleDay);
        });
    });

    async function fetchSchedule(day) {
        const loadingEl = document.getElementById('schedule-loading');
        const listEl = document.getElementById('schedule-list');
        const weekBadge = document.getElementById('schedule-week-badge');

        if (loadingEl) loadingEl.classList.remove('hidden');
        if (listEl) listEl.innerHTML = '';

        try {
            const res = await fetch(`/api/schedule?day=${day}`);
            const data = await res.json();
            if (loadingEl) loadingEl.classList.add('hidden');

            if (!data.success || !data.lessons || data.lessons.length === 0) {
                listEl.innerHTML = '<div class="empty-state"><div class="empty-icon">🎉</div><p>У цей день пар немає! Відпочивайте.</p></div>';
                return;
            }

            if (weekBadge) weekBadge.textContent = `Тиждень ${data.week} • ${data.day_name}`;

            listEl.innerHTML = data.lessons.map(l => {
                const linkBtn = l.link_url
                    ? `<a href="${l.link_url}" target="_blank" class="lesson-join-btn">🔗 Приєднатися</a>`
                    : '<span style="font-size:12px;color:var(--hint-color);">Посилання відсутнє</span>';

                return `
                    <div class="schedule-card">
                        <div class="lesson-header">
                            <span class="lesson-time">Пара ${l.pair_number} (${l.time_start} - ${l.time_end})</span>
                            <span class="lesson-type">${escapeHtml(l.type || 'Пара')}</span>
                        </div>
                        <h4 class="lesson-title">${escapeHtml(l.subject)}</h4>
                        <div class="lesson-teacher">👤 ${escapeHtml(l.teacher || 'Викладач не вказаний')}</div>
                        ${linkBtn}
                    </div>
                `;
            }).join('');
        } catch (err) {
            if (loadingEl) loadingEl.classList.add('hidden');
            listEl.innerHTML = '<div class="empty-state"><p>Не вдалося завантажити розклад</p></div>';
        }
    }

    // --- Deadlines Tab Logic ---
    async function fetchDeadlines() {
        const listEl = document.getElementById('deadlines-list');
        const countBadge = document.getElementById('deadlines-count');
        try {
            const res = await fetch('/api/deadlines');
            const data = await res.json();
            if (!data.success || !data.deadlines || data.deadlines.length === 0) {
                listEl.innerHTML = '<div class="empty-state"><div class="empty-icon">✅</div><p>Активних дедлайнів немає. Все здано!</p></div>';
                if (countBadge) countBadge.textContent = '0';
                return;
            }

            if (countBadge) countBadge.textContent = data.total;

            listEl.innerHTML = data.deadlines.map(d => {
                const linkAttr = d.alternate_link ? `onclick="window.open('${d.alternate_link}', '_blank')"` : '';
                return `
                    <div class="deadline-card" ${linkAttr} style="${d.alternate_link ? 'cursor:pointer;' : ''}">
                        <div class="deadline-meta">
                            <span class="deadline-course">${escapeHtml(d.course_name || 'Предмет')}</span>
                            <span class="deadline-due">⏰ ${d.due_time ? d.due_time.substring(0, 16) : 'Без дедлайну'}</span>
                        </div>
                        <h4 class="deadline-title">${escapeHtml(d.title)}</h4>
                    </div>
                `;
            }).join('');
        } catch (err) {
            listEl.innerHTML = '<div class="empty-state"><p>Не вдалося завантажити дедлайни</p></div>';
        }
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Initialize UI
    renderLabsGrid();
    updatePriorityPreview();
    fetchQueue();

    // Auto-polling for real-time queue updates every 4 seconds
    pollInterval = setInterval(() => {
        const queueTabActive = document.getElementById('tab-queue')?.classList.contains('active');
        if (queueTabActive) fetchQueue();
    }, 4000);
});
