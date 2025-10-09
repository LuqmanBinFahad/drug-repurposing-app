document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    const suggestionsContainer = document.getElementById('suggestions');
    
    // Mock drug suggestions
    const drugSuggestions = [
        'Aspirin', 'Metformin', 'Ibuprofen', 'Lisinopril', 'Atorvastatin',
        'Levothyroxine', 'Amlodipine', 'Simvastatin', 'Omeprazole', 'Sertraline'
    ];
    
    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase();
        
        if (query.length > 1) {
            const filteredSuggestions = drugSuggestions.filter(drug => 
                drug.toLowerCase().includes(query)
            );
            
            if (filteredSuggestions.length > 0) {
                suggestionsContainer.innerHTML = '';
                filteredSuggestions.slice(0, 5).forEach(suggestion => {
                    const suggestionItem = document.createElement('div');
                    suggestionItem.className = 'suggestion-item';
                    suggestionItem.textContent = suggestion;
                    suggestionItem.addEventListener('click', function() {
                        searchInput.value = suggestion;
                        suggestionsContainer.style.display = 'none';
                    });
                    suggestionsContainer.appendChild(suggestionItem);
                });
                suggestionsContainer.style.display = 'block';
            } else {
                suggestionsContainer.style.display = 'none';
            }
        } else {
            suggestionsContainer.style.display = 'none';
        }
    });
    
    // Hide suggestions when clicking outside
    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !suggestionsContainer.contains(e.target)) {
            suggestionsContainer.style.display = 'none';
        }
    });
});