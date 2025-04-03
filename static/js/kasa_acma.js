const kasaAcButton = document.getElementById('kasa-ac-button');
const skinDonmeAlani = document.getElementById('skin-donme-alani');
const skinResmi = document.getElementById('skin-resmi');

kasaAcButton.addEventListener('click', () => {
    kasaAcButton.disabled = true; // Butona tekrar tıklanmasını engelle
    skinDonmeAlani.style.animation = 'donme 3s ease-out 1'; // Animasyonu başlat

    fetch("{% url 'kasa_ac_ajax' kasa.id %}")
        .then(response => response.json())
        .then(data => {
            setTimeout(() => {
                skinResmi.src = data.skin_resim; // Resmi ayarla
                skinDonmeAlani.style.animation = ''; // Animasyonu durdur
                kasaAcButton.disabled = false; // Butonu tekrar etkinleştir
            }, 3000); // 3 saniye sonra
        });
});

// CSS animasyonu
const styleSheet = document.createElement("style");
styleSheet.type = "text/css";
styleSheet.innerText = `
@keyframes donme {
    0% { transform: translateX(0); }
    100% { transform: translateX(-600px); } /* Skin resmi genişliğine göre ayarlanmalı */
}
`;
document.head.appendChild(styleSheet);