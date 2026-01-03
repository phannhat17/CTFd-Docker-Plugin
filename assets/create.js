CTFd.plugin.run((_CTFd) => {
    // console.log(('[Container Plugin] CTFd.plugin.run callback executing 2!');
    
    const $ = _CTFd.lib.$;
    const md = _CTFd.lib.markdown();
    
    // console.log(('[Container Plugin] jQuery loaded:', typeof $ !== 'undefined');
    // console.log(('[Container Plugin] DOM readyState:', document.readyState);
    
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

    // Parse flag pattern and auto-fill hidden fields
    function parseFlagPattern() {
        // console.log(('[Container Plugin] parseFlagPattern() called');
        const patternInput = document.getElementById('flag_pattern');
        const preview = document.getElementById('flag_pattern_preview');
        
        // console.log(('[Container Plugin] patternInput:', patternInput);
        // console.log(('[Container Plugin] preview:', preview);
        
        if (!patternInput || !preview) {
            console.warn('[Container Plugin] Missing elements - patternInput or preview');
            return; // Guard clause
        }
        
        const pattern = patternInput.value;
        // console.log(('[Container Plugin] Pattern value:', pattern);
    
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

    // Initialize all event listeners
    // Note: CTFd.plugin.run already waits for DOM, no need for DOMContentLoaded
    // console.log(('[Container Plugin] Initializing event listeners...');
    (function() {
        // console.log(('[Container Plugin] Init function executing!');
        
        // Flag pattern preview
        const flagPatternInput = document.getElementById('flag_pattern');
        // console.log(('[Container Plugin] Flag pattern input:', flagPatternInput);
        if (flagPatternInput) {
            flagPatternInput.addEventListener('input', parseFlagPattern);
            // Parse initial value
            try {
                parseFlagPattern();
                // console.log(('[Container Plugin] Initial flag pattern parsed');
            } catch (e) {
                console.error('[Container Plugin] Error parsing flag pattern:', e);
            }
        } else {
            console.error('[Container Plugin] Flag pattern input not found!');
        }
        
        // Toggle between standard and dynamic scoring
        const scoringTypeSelect = document.getElementById('scoring_type');
        // console.log(('[Container Plugin] Scoring type select:', scoringTypeSelect);
        if (scoringTypeSelect) {
            scoringTypeSelect.addEventListener('change', function() {
                // console.log(('[Container Plugin] Scoring type changed to:', this.value);
                const scoringType = this.value;
                const standardSection = document.getElementById('standard-scoring');
                const dynamicSection = document.getElementById('dynamic-scoring');
                
                // console.log(('[Container Plugin] Standard section:', standardSection);
                // console.log(('[Container Plugin] Dynamic section:', dynamicSection);
                
                if (!standardSection || !dynamicSection) {
                    console.error('[Container Plugin] Sections not found!');
                    return;
                }
                
                if (scoringType === 'standard') {
                    standardSection.style.display = 'block';
                    dynamicSection.style.display = 'none';
                    
                    // Set required on standard fields
                    const standardValue = document.getElementById('standard_value');
                    if (standardValue) {
                        standardValue.required = true;
                        standardValue.disabled = false;
                    }
                    
                    // Disable dynamic fields
                    const dynamicFields = ['dynamic_initial', 'dynamic_decay', 'dynamic_minimum', 'decay_function'];
                    dynamicFields.forEach(id => {
                        const field = document.getElementById(id);
                        if (field) {
                            field.required = false;
                            field.disabled = true;
                        }
                    });
                    
                    // console.log(('[Container Plugin] Switched to standard scoring');
                } else {
                    standardSection.style.display = 'none';
                    dynamicSection.style.display = 'block';
                    
                    // Disable standard field
                    const standardValue = document.getElementById('standard_value');
                    if (standardValue) {
                        standardValue.required = false;
                        standardValue.disabled = true;
                    }
                    
                    // Enable dynamic fields
                    const dynamicFields = [
                        { id: 'dynamic_initial', required: true },
                        { id: 'dynamic_decay', required: true },
                        { id: 'dynamic_minimum', required: true },
                        { id: 'decay_function', required: false }
                    ];
                    dynamicFields.forEach(field => {
                        const el = document.getElementById(field.id);
                        if (el) {
                            el.required = field.required;
                            el.disabled = false;
                        }
                    });
                    
                    // console.log(('[Container Plugin] Switched to dynamic scoring');
                }
            });
            
            // Trigger change event to set initial state
            try {
                scoringTypeSelect.dispatchEvent(new Event('change'));
                // console.log(('[Container Plugin] Initial scoring type event dispatched');
            } catch (e) {
                console.error('[Container Plugin] Error dispatching scoring type event:', e);
            }
        } else {
            console.error('[Container Plugin] Scoring type select not found!');
        }
        
        // console.log(('[Container Plugin] Initialization complete');
    })(); // IIFE - execute immediately

    // Load Docker images
    // console.log(('[Container Plugin] Loading Docker images...');
    var containerImage = document.getElementById("container-image");
    var containerImageDefault = document.getElementById("container-image-default");

    if (containerImage && containerImageDefault) {
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
                // console.log(('[Container Plugin] Loaded', data.images.length, 'Docker images');
            }
        })
        .catch(error => {
            console.error("[Container Plugin] Error loading images:", error);
            containerImageDefault.innerHTML = "Error loading images";
        });
    } else {
        console.warn('[Container Plugin] Container image elements not found');
    }
    
    // console.log(('[Container Plugin] Plugin initialization complete!');
});
