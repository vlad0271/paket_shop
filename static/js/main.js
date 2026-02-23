import { initCarousel } from './carousel.js';
import { initConstructor } from './constructor.js';
import { initCalculator } from './calculator.js';
import { initOrderForm } from './order.js';

document.addEventListener('DOMContentLoaded', async () => {
    await initCarousel();
    await initConstructor();
    initCalculator();
    initOrderForm();
    initVideoHandling();
    loadContacts();
});

async function loadContacts() {
    const response = await fetch('/api/contacts');
    if (!response.ok) return;
    const { phone, email } = await response.json();

    const phoneEl = document.getElementById('contact-phone');
    phoneEl.href = `tel:${phone}`;
    phoneEl.textContent = phone;

    const emailEl = document.getElementById('contact-email');
    emailEl.href = `mailto:${email}`;
    emailEl.textContent = email;
}

function initVideoHandling() {
    const video = document.getElementById('promo-video');
    if (!video) return;

    video.addEventListener('error', function(e) {
        console.warn('Ошибка загрузки видео:', e);
        const videoContainer = video.parentElement;
        if (videoContainer) {
            video.style.display = 'none';
            const errorMsg = document.createElement('div');
            errorMsg.style.cssText = 'padding: 2rem; text-align: center; color: #666; background: #f8f8f8; border-radius: 8px;';
            errorMsg.innerHTML = '<p>Видео временно недоступно</p><p style="font-size: 0.875rem; margin-top: 0.5rem;">Пожалуйста, попробуйте позже</p>';
            videoContainer.appendChild(errorMsg);
        }
    });

    const btn = document.getElementById('volume-btn');
    const iconOff = document.getElementById('volume-icon-off');
    const iconOn = document.getElementById('volume-icon-on');
    if (!btn) return;

    btn.addEventListener('click', () => {
        if (video.muted) {
            video.muted = false;
            video.volume = 1.0;
        } else {
            video.muted = true;
        }
        iconOff.style.display = video.muted ? 'block' : 'none';
        iconOn.style.display  = video.muted ? 'none'  : 'block';
        btn.setAttribute('aria-label', video.muted ? 'Включить звук' : 'Выключить звук');
    });
}
