import wave, struct, os
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "audio", "markers"))
os.makedirs(OUT, exist_ok=True)
branches = ["D","Temple","Orc","Lair","Swamp","Shoals","Snake","Spider","Slime",
            "Vaults","Crypt","Tomb","Depths","Zot","Hell","Dis","Geh","Coc","Tar",
            "Abyss","Pan","Sewer","Ossuary","Bailey","IceCv","Volcano","WizLab"]
tokens = ["state__branch_" + b for b in branches] + ["state__hp_low", "state__hp_ok", "state__player_death"]
for t in tokens:
    w = wave.open(os.path.join(OUT, t + ".wav"), "w")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
    w.writeframes(struct.pack("<h", 0))
    w.close()
print("markers:", len(tokens))
