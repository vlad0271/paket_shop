import { fetchImages } from './api.js';

let currentIndex = 0;
let images = [];

const PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='280' height='280'%3E%3Crect fill='%23f0f0f0' width='280' height='280'/%3E%3C/svg%3E";

export async function initCarousel() {
    try {
        images = await fetchImages();
        renderCarousel();
        setupControls();
    } catch (error) {
        console.error('Ошибка инициализации карусели:', error);
    }
}

function renderCarousel() {
    const track = document.getElementById('carousel-track');
    track.innerHTML = '';

    if (images.length === 0) {
        track.innerHTML = '<div style="text-align: center; padding: 2rem; color: #999;">Изображения не найдены</div>';
        return;
    }

    images.forEach(url => {
        const item = document.createElement('div');
        item.className = 'carousel-item';

        const img = document.createElement('img');
        img.src = url;
        img.alt = '';
        img.loading = 'lazy';
        img.onerror = function() {
            this.src = PLACEHOLDER;
            this.onerror = null;
        };

        item.appendChild(img);
        track.appendChild(item);
    });

    updateCarousel();
}

function setupControls() {
    document.querySelector('.carousel-btn.prev').addEventListener('click', () => {
        currentIndex = (currentIndex - 1 + images.length) % images.length;
        updateCarousel();
    });

    document.querySelector('.carousel-btn.next').addEventListener('click', () => {
        currentIndex = (currentIndex + 1) % images.length;
        updateCarousel();
    });
}

function updateCarousel() {
    const track = document.getElementById('carousel-track');
    const firstItem = track.querySelector('.carousel-item');
    const itemWidth = firstItem ? firstItem.offsetWidth : 280;
    const gap = 24;
    const offset = -currentIndex * (itemWidth + gap);
    track.style.transform = `translateX(${offset}px)`;
}
