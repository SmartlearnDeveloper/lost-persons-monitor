(function () {
    const STORAGE_KEY = 'lpm_auth_state';

    function loginUrl() {
        return window.LPM_AUTH_LOGIN_URL || '/login';
    }

    function getStored() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY) || sessionStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (error) {
            console.warn('No se pudo leer el token almacenado', error);
            return null;
        }
    }

    function setStored(data) {
        const serialized = JSON.stringify(data || {});
        localStorage.setItem(STORAGE_KEY, serialized);
        sessionStorage.setItem(STORAGE_KEY, serialized);
    }

    function clearStored() {
        localStorage.removeItem(STORAGE_KEY);
        sessionStorage.removeItem(STORAGE_KEY);
    }

    function isAuthenticated() {
        const data = getStored();
        return Boolean(data && data.access_token);
    }

    function redirectToLogin() {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `${loginUrl()}?next=${next}`;
    }

    function requireAuth() {
        if (!isAuthenticated()) {
            redirectToLogin();
        }
    }

    async function authFetch(input, init = {}) {
        const headers = new Headers(init.headers || {});
        const stored = getStored();
        if (stored && stored.access_token) {
            headers.set('Authorization', `Bearer ${stored.access_token}`);
        }
        const response = await fetch(input, { ...init, headers });
        if (response.status === 401) {
            clearStored();
            redirectToLogin();
            throw new Error('Sesión expirada. Inicia sesión nuevamente.');
        }
        return response;
    }

    async function authJson(url, options = {}) {
        const response = await authFetch(url, options);
        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || `Request failed (${response.status})`);
        }
        return response.json();
    }

    function populateSessionBadge(selector) {
        const container = document.querySelector(selector);
        if (!container) return;
        const data = getStored();
        const loginLink = container.querySelector('[data-lpm-login]');
        const logoutForm = container.querySelector('[data-lpm-logout]');
        const usernameBadge = container.querySelector('[data-lpm-username]');
        if (usernameBadge) {
            usernameBadge.textContent = data?.username ? `Sesión: ${data.username}` : '';
        }
        if (isAuthenticated()) {
            if (loginLink) loginLink.classList.add('d-none');
            if (logoutForm) logoutForm.classList.remove('d-none');
        } else {
            if (loginLink) loginLink.classList.remove('d-none');
            if (logoutForm) logoutForm.classList.add('d-none');
        }
    }

    window.LPMAuth = {
        STORAGE_KEY,
        loginUrl,
        getAuthData: getStored,
        setAuthData: setStored,
        clearAuthData: clearStored,
        isAuthenticated,
        requireAuth,
        authFetch,
        authJson,
        populateSessionBadge,
    };
})();
