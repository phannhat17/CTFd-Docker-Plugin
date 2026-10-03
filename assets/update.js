CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;
    const md = _CTFd.lib.markdown();
    
    // Disable flag modal popup for container challenges
    // Container challenges auto-generate flags based on flag_mode setting
    window.challenge = window.challenge || {};
    window.challenge.data = window.challenge.data || {};
    window.challenge.data.flags = [];
});

// Parse flag pattern and auto-fill hidden fields
function renderFlagPreview(preview, label, code, color) {
    // textContent (not innerHTML): the pattern is admin supplied input and
    // must never be interpreted as markup.
    preview.textContent = '';
    preview.append(label);
    const codeEl = document.createElement('code');
    codeEl.textContent = code;
    preview.appendChild(codeEl);
    preview.style.color = color;
}

function parseFlagPattern() {
    const input = document.getElementById('flag_pattern');
    const preview = document.getElementById('flag_pattern_preview');
    if (!input || !preview) return;

    const pattern = input.value;

    // Check for random pattern: <ran_N> where N is the length
    const randomMatch = pattern.match(/<ran_(\d+)>/);

    if (randomMatch) {
        const randomLength = parseInt(randomMatch[1], 10);
        const parts = pattern.split(randomMatch[0]);

        document.getElementById('flag_mode').value = 'random';
        document.getElementById('flag_prefix').value = parts[0] || '';
        document.getElementById('flag_suffix').value = parts[1] || '';
        document.getElementById('random_flag_length').value = randomLength;

        const exampleRandom = 'x'.repeat(randomLength);
        renderFlagPreview(
            preview,
            `\u2713 Random mode: `,
            `${parts[0] || ''}${exampleRandom}${parts[1] || ''} (${randomLength} random chars)`,
            '#17a2b8'
        );
    } else {
        document.getElementById('flag_mode').value = 'static';
        document.getElementById('flag_prefix').value = pattern;
        document.getElementById('flag_suffix').value = '';
        document.getElementById('random_flag_length').value = 0;

        renderFlagPreview(preview, `\u2713 Static mode: `, `${pattern} (same for all teams)`, '#28a745');
    }
}

// Add event listener for flag pattern input
document.addEventListener('DOMContentLoaded', function() {
    const flagPatternInput = document.getElementById('flag_pattern');
    if (flagPatternInput) {
        flagPatternInput.addEventListener('input', parseFlagPattern);
        // Parse initial value after it's been set
        setTimeout(parseFlagPattern, 100);
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
.then(response => response.json())
.then(data => {
    if (data.error) {
        containerImageDefault.textContent = data.error;
    } else {
        for (var i = 0; i < data.images.length; i++) {
            var opt = document.createElement("option");
            opt.value = data.images[i];
            opt.textContent = data.images[i];
            containerImage.appendChild(opt);
        }
        containerImageDefault.innerHTML = "Choose an image...";
        containerImage.disabled = false;
        
        // Set selected image from challenge data
        if (typeof container_image_selected !== 'undefined') {
            containerImage.value = container_image_selected;
        }
    }
})
.catch(error => {
    console.error("Error loading images:", error);
    containerImageDefault.textContent = "Error loading images";
});

// Set connection type value from challenge data
var connectType = document.getElementById("connect-type");
if (connectType && typeof container_connection_type_selected !== 'undefined') {
    connectType.value = container_connection_type_selected;
}
