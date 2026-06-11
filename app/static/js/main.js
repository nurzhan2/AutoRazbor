// Gallery thumbnails
document.querySelectorAll('.gallery-thumbs .thumb').forEach(thumb => {
    thumb.addEventListener('click', function() {
        document.querySelectorAll('.gallery-thumbs .thumb').forEach(t => t.classList.remove('active'));
        this.classList.add('active');
        const main = document.getElementById('main-img');
        if (main) main.src = this.src;
    });
});

// Auto-dismiss alerts
document.querySelectorAll('.alert').forEach(alert => {
    setTimeout(() => {
        alert.style.opacity = '0';
        alert.style.transition = 'opacity .4s';
        setTimeout(() => alert.remove(), 400);
    }, 5000);
});

// Toggle favorite product
async function toggleFav(productId, btn) {
    try {
        const res = await fetch(`/favorites/product/${productId}/toggle`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'added') {
            btn.innerHTML = '❤️ В избранном';
            btn.classList.add('fav-active');
        } else {
            btn.innerHTML = '🤍 В избранное';
            btn.classList.remove('fav-active');
        }
    } catch(e) { console.error(e); }
}
