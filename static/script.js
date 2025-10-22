// Autocomplete functionality
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    const suggestionsContainer = document.getElementById('suggestions-container');
    
    // Sample drug database for autocomplete
    const drugDatabase = [
        "Metformin", "Aspirin", "Sildenafil", "Thalidomide", "Rapamycin",
        "Doxycycline", "Losartan", "Atorvastatin", "Levothyroxine", "Amlodipine",
        "Simvastatin", "Omeprazole", "Sertraline", "Ibuprofen", "Acetaminophen",
        "Lisinopril", "Atenolol", "Hydrochlorothiazide", "Furosemide", "Digoxin"
    ];
    
    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase();
        if (query.length < 2) {
            suggestionsContainer.style.display = 'none';
            return;
        }
        
        const filtered = drugDatabase.filter(drug => 
            drug.toLowerCase().includes(query)
        ).slice(0, 10); // Limit to 10 suggestions
        
        if (filtered.length > 0) {
            suggestionsContainer.innerHTML = '';
            filtered.forEach(drug => {
                const suggestion = document.createElement('div');
                suggestion.className = 'suggestion-item';
                suggestion.textContent = drug;
                suggestion.addEventListener('click', function() {
                    searchInput.value = drug;
                    suggestionsContainer.style.display = 'none';
                    // Submit the form automatically
                    document.getElementById('search-form').submit();
                });
                suggestionsContainer.appendChild(suggestion);
            });
            suggestionsContainer.style.display = 'block';
        } else {
            suggestionsContainer.style.display = 'none';
        }
    });
    
    // Hide suggestions when clicking outside
    document.addEventListener('click', function(e) {
        if (!suggestionsContainer.contains(e.target) && e.target !== searchInput) {
            suggestionsContainer.style.display = 'none';
        }
    });
    
    // Load favorite status on page load
    loadFavoriteStatus();
    updateFavoritesDisplay();
});

// Favorite functionality
function addToFavorites(drugName) {
    let favorites = JSON.parse(localStorage.getItem('drug_favorites') || '[]');
    if (!favorites.includes(drugName)) {
        favorites.push(drugName);
        localStorage.setItem('drug_favorites', JSON.stringify(favorites));
        showToast(`${drugName} added to favorites`, 'success');
        updateFavoritesDisplay();
    }
}

function removeFromFavorites(drugName) {
    let favorites = JSON.parse(localStorage.getItem('drug_favorites') || '[]');
    favorites = favorites.filter(name => name !== drugName);
    localStorage.setItem('drug_favorites', JSON.stringify(favorites));
    showToast(`${drugName} removed from favorites`, 'info');
    updateFavoritesDisplay();
}

function loadFavoriteStatus() {
    const favorites = JSON.parse(localStorage.getItem('drug_favorites') || '[]');
    document.querySelectorAll('.favorite-btn').forEach(button => {
        const drugName = button.getAttribute('data-drug');
        if (favorites.includes(drugName)) {
            button.innerHTML = '<i class="fas fa-star"></i>';
        } else {
            button.innerHTML = '<i class="far fa-star"></i>';
        }
    });
}

function updateFavoritesDisplay() {
    const favorites = JSON.parse(localStorage.getItem('drug_favorites') || '[]');
    const container = document.getElementById('favorites-list');
    const noFavMsg = document.getElementById('no-favorites-message');
    
    if (favorites.length > 0) {
        noFavMsg.style.display = 'none';
        container.innerHTML = '';
        favorites.forEach(fav => {
            const favItem = document.createElement('div');
            favItem.className = 'favorite-item';
            favItem.innerHTML = `
                <span>${fav}</span>
                <button class="remove-fav-btn" onclick="removeFromFavorites('${fav}')">Remove</button>
            `;
            container.appendChild(favItem);
        });
    } else {
        noFavMsg.style.display = 'block';
        container.innerHTML = '';
    }
}

// Toast notification system
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    // Add close button
    const closeBtn = document.createElement('span');
    closeBtn.className = 'toast-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = () => toast.remove();
    
    toast.appendChild(closeBtn);
    toastContainer.appendChild(toast);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.remove();
        }
    }, 5000);
}

// Dark mode toggle
function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    const isDarkMode = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDarkMode);
    
    // Update button text
    const darkModeBtn = document.getElementById('dark-mode-toggle');
    if (darkModeBtn) {
        darkModeBtn.textContent = isDarkMode ? 'Light Mode' : 'Dark Mode';
    }
}

// Check for saved dark mode preference
if (localStorage.getItem('darkMode') === 'true') {
    document.body.classList.add('dark-mode');
}

// Dynamically load dark mode CSS file for maintainability
if (!document.getElementById('dark-mode-css')) {
    const darkModeLink = document.createElement('link');
    darkModeLink.id = 'dark-mode-css';
    darkModeLink.rel = 'stylesheet';
    darkModeLink.href = '/static/dark-mode.css'; // Ensure this path matches your project structure
    document.head.appendChild(darkModeLink);
}

// Add dark mode toggle button to header if it doesn't exist
if (!document.getElementById('dark-mode-toggle')) {
    const header = document.querySelector('.header');
    if (header) {
        const darkModeBtn = document.createElement('button');
        darkModeBtn.id = 'dark-mode-toggle';
        darkModeBtn.textContent = localStorage.getItem('darkMode') === 'true' ? 'Light Mode' : 'Dark Mode';
        darkModeBtn.style.position = 'absolute';
        darkModeBtn.style.top = '10px';
        darkModeBtn.style.left = '10px';
        darkModeBtn.style.background = 'rgba(255, 255, 255, 0.2)';
        darkModeBtn.style.color = 'white';
        darkModeBtn.style.border = 'none';
        darkModeBtn.style.padding = '5px 10px';
        darkModeBtn.style.borderRadius = '5px';
        darkModeBtn.style.cursor = 'pointer';
        darkModeBtn.onclick = toggleDarkMode;
        header.appendChild(darkModeBtn);
    }
}

// Loading states and skeleton screens
function showLoading(elementId, message) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = `
            <div class="loading-skeleton">
                <div class="skeleton-line"></div>
                <div class="skeleton-line short"></div>
                <div class="skeleton-line"></div>
            </div>
            <p>${message}</p>
        `;
    }
}

function hideLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = '';
    }
}

// Add skeleton styles if not present
if (!document.getElementById('skeleton-styles')) {
    const skeletonStyles = document.createElement('style');
    skeletonStyles.id = 'skeleton-styles';
    skeletonStyles.textContent = `
        .loading-skeleton {
            padding: 20px;
        }
        .skeleton-line {
            height: 20px;
            background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
            background-size: 200% 100%;
            animation: loading 1.5s infinite;
            margin-bottom: 10px;
            border-radius: 4px;
        }
        .skeleton-line.short {
            width: 60%;
        }
        @keyframes loading {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
    `;
    document.head.appendChild(skeletonStyles);
}

// Service Worker registration for PWA
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(function(registration) {
                console.log('ServiceWorker registration successful');
            })
            .catch(function(err) {
                console.log('ServiceWorker registration failed');
            });
    });
}

// Check online/offline status
window.addEventListener('load', function() {
    const updateOnlineStatus = () => {
        const status = document.getElementById('online-status');
        if (status) {
            status.textContent = navigator.onLine ? 'Online' : 'Offline';
            status.className = navigator.onLine ? 'online' : 'offline';
        }
    };

    window.addEventListener('online', updateOnlineStatus);
    window.addEventListener('offline', updateOnlineStatus);
    updateOnlineStatus();
});
// ... (keep existing script content like autocomplete, favorites, etc.) ...

// Add link to Compare page in header or somewhere prominent (optional, for easy access)
// You can add this dynamically or just update the HTML
if (window.location.pathname !== '/compare') {
    const compareLink = document.createElement('a');
    compareLink.href = '/compare';
    compareLink.textContent = 'Compare Drugs';
    compareLink.className = 'compare-link-header'; // Add CSS class if needed
    // You might want to append this to the header or navigation
    // e.g., document.querySelector('.header').appendChild(compareLink);
}

// ... (rest of your existing script functions remain) ...