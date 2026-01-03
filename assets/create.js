CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;
    const md = _CTFd.lib.markdown();
    
    // Disable flag modal popup for container challenges
    // Container challenges auto-generate flags based on flag_mode setting
    window.challenge = window.challenge || {};
    window.challenge.data = window.challenge.data || {};
    window.challenge.data.flags = [];
    
    // Override flag creation - container challenges don't need manual flags
    const originalSubmit = window.challenge?.submit;
    if (originalSubmit) {
        window.challenge.submit = function(preview) {
            // Skip flag modal, directly submit
            return originalSubmit.call(this, preview);
        };
    }
});

// Parse flag pattern and auto-fill hidden fields
function parseFlagPattern() {
    const pattern = document.getElementById('flag_pattern').value;
    const preview = document.getElementById('flag_pattern_preview');
    
    // Check for random pattern: <ran_N> where N is the length
    const randomMatch = pattern.match(/<ran_(\d+)>/);
    
    if (randomMatch) {
        // Random mode detected
        const randomLength = parseInt(randomMatch[1]);
        const parts = pattern.split(randomMatch[0]);
        
        document.getElementById('flag_mode').value = 'random';
        document.getElementById('flag_prefix').value = parts[0] || '';
        document.getElementById('flag_suffix').value = parts[1] || '';
        document.getElementById('random_flag_length').value = randomLength;
        
        // Generate preview
        const exampleRandom = 'x'.repeat(randomLength);
        preview.innerHTML = `✓ Random mode: <code>${parts[0]}${exampleRandom}${parts[1]}</code> (${randomLength} random chars)`;
        preview.style.color = '#17a2b8';
    } else {
        // Static mode
        document.getElementById('flag_mode').value = 'static';
        document.getElementById('flag_prefix').value = pattern;
        document.getElementById('flag_suffix').value = '';
        document.getElementById('random_flag_length').value = 0;
        
        preview.innerHTML = `✓ Static mode: <code>${pattern}</code> (same for all teams)`;
        preview.style.color = '#28a745';
    }
}

// Add event listener for flag pattern input
document.addEventListener('DOMContentLoaded', function() {
    const flagPatternInput = document.getElementById('flag_pattern');
    if (flagPatternInput) {
        flagPatternInput.addEventListener('input', parseFlagPattern);
        // Parse initial value
        parseFlagPattern();
    }
});

// Toggle between standard and dynamic scoring
document.getElementById('scoring_type').addEventListener('change', function() {
    const scoringType = this.value;
    const standardSection = document.getElementById('standard-scoring');
    const dynamicSection = document.getElementById('dynamic-scoring');
    
    if (scoringType === 'standard') {
        standardSection.style.display = 'block';
        dynamicSection.style.display = 'none';
        
        // Set required on standard fields
        document.getElementById('standard_value').required = true;
        document.getElementById('dynamic_initial').required = false;
        document.getElementById('dynamic_decay').required = false;
        document.getElementById('dynamic_minimum').required = false;
        
        // Disable dynamic fields so they won't be submitted
        document.getElementById('dynamic_initial').disabled = true;
        document.getElementById('dynamic_decay').disabled = true;
        document.getElementById('dynamic_minimum').disabled = true;
        document.getElementById('decay_function').disabled = true;
        
        // Enable standard field
        document.getElementById('standard_value').disabled = false;
    } else {
        standardSection.style.display = 'none';
        dynamicSection.style.display = 'block';
        
        // Set required on dynamic fields
        document.getElementById('standard_value').required = false;
        document.getElementById('dynamic_initial').required = true;
        document.getElementById('dynamic_decay').required = true;
        document.getElementById('dynamic_minimum').required = true;
        
        // Disable standard field so it won't be submitted
        document.getElementById('standard_value').disabled = true;
        
        // Enable dynamic fields
        document.getElementById('dynamic_initial').disabled = false;
        document.getElementById('dynamic_decay').disabled = false;
        document.getElementById('dynamic_minimum').disabled = false;
        document.getElementById('decay_function').disabled = false;
    }
});

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Trigger scoring type change to set initial state
    const scoringTypeSelect = document.getElementById('scoring_type');
    if (scoringTypeSelect) {
        // Fire change event to initialize disabled states
        scoringTypeSelect.dispatchEvent(new Event('change'));
    }
});

// Load Docker images
var containerImage = document.getElementById("container-image");
var containerImageDefault = document.getElementById("container-image-default");

fetch("/admin/containers/api/images", {
    method: "GET",
    headers: {
        "Accept": "application/json",
        "CSRF-Token": init.csrfNonce
    }
})
.then(response => {
    if (!response.ok) {
        return Promise.reject("Error fetching images");
    }
    return response.json();
})
.then(data => {
    if (data.error) {
        containerImageDefault.innerHTML = data.error;
    } else {
        for (var i = 0; i < data.images.length; i++) {
            var opt = document.createElement("option");
            opt.value = data.images[i];
            opt.innerHTML = data.images[i];
            containerImage.appendChild(opt);
        }
        containerImageDefault.innerHTML = "Choose an image...";
        containerImage.removeAttribute("disabled");
    }
})
.catch(error => {
    console.error("Error loading images:", error);
    containerImageDefault.innerHTML = "Error loading images";
});
