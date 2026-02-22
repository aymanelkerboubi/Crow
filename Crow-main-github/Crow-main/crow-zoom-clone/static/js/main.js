// Real-time meeting updates (simulated)
// Settings Page Functionality
function initSettingsPage() {
    console.log('Settings page initialized');
    
    // Auto-save indicator
    const form = document.getElementById('settings-form');
    if (form) {
        let isDirty = false;
        const inputs = form.querySelectorAll('input, textarea, select');
        
        inputs.forEach(input => {
            input.addEventListener('input', () => {
                isDirty = true;
                showAutoSaveIndicator();
            });
        });
        
        form.addEventListener('submit', () => {
            isDirty = false;
            hideAutoSaveIndicator();
        });
    }
    
    // Initialize tooltips
    const tooltips = document.querySelectorAll('[data-tooltip]');
    tooltips.forEach(el => {
        el.addEventListener('mouseenter', (e) => {
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip';
            tooltip.textContent = e.target.dataset.tooltip;
            document.body.appendChild(tooltip);
            
            const rect = e.target.getBoundingClientRect();
            tooltip.style.left = `${rect.left + rect.width/2}px`;
            tooltip.style.top = `${rect.top - 40}px`;
            tooltip.style.transform = 'translateX(-50%)';
            
            e.target._tooltip = tooltip;
        });
        
        el.addEventListener('mouseleave', (e) => {
            if (e.target._tooltip) {
                e.target._tooltip.remove();
            }
        });
    });
}

function showAutoSaveIndicator() {
    let indicator = document.getElementById('auto-save-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'auto-save-indicator';
        indicator.className = 'auto-save-indicator';
        indicator.textContent = 'Changes not saved';
        document.querySelector('.settings-header').appendChild(indicator);
    }
}

function hideAutoSaveIndicator() {
    const indicator = document.getElementById('auto-save-indicator');
    if (indicator) {
        indicator.remove();
    }
}

// Load settings page functionality when DOM is ready
if (document.querySelector('.settings-container')) {
    document.addEventListener('DOMContentLoaded', initSettingsPage);
}