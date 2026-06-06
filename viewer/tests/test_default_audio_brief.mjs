// Mirror of viewer.html audio brief-vs-full resolution + first-view default.
function decide(p) {
  const {hasMdKoAudioBrief=false, hasMdKoAudio=false, hasMdKoExplained=false,
         hasMdKo=false, hasMdEn=false,
         audioPref=null, explainedPref=null, langPref=null, audioFull=false} = p;
  let langKo = (langPref === 'ko');
  let audioMode = false, explainedMode = false;
  if ((hasMdKoExplained) && explainedPref === 'true') explainedMode = true;
  if ((hasMdKoAudio || hasMdKoAudioBrief) && audioPref === 'true') { audioMode = true; explainedMode = false; langKo = true; }
  if (!audioMode && !explainedMode) {
    const allowKo = langPref !== 'en';
    const hasAudioText = hasMdKoAudio || hasMdKoAudioBrief;
    if (hasAudioText && audioPref === null && allowKo) { audioMode = true; langKo = true; }
    else if (audioPref === null && explainedPref === null && allowKo && hasMdKoExplained) { explainedMode = true; langKo = true; }
    else if (langPref === null && hasMdKo) { langKo = true; }
  }
  // brief when brief exists AND (not switched to 전체 OR no full audio to switch to)
  const audioUsesBrief = audioMode && hasMdKoAudioBrief && (!audioFull || !hasMdKoAudio);
  if (audioMode) return audioUsesBrief ? 'AUDIO_BRIEF' : 'AUDIO_FULL';
  if (explainedMode) return 'EXPLAINED';
  return langKo ? (hasMdKo ? 'ORIG(ko)' : 'ORIG(en)') : (hasMdEn ? 'ORIG(en)' : 'ORIG(ko)');
}
const T = (d,g,w)=>{const ok=g===w;console.log(`${ok?'✓':'✗'} ${d}: ${g}${ok?'':' WANT '+w}`);if(!ok)process.exitCode=1;};

const FULL = {hasMdKoAudioBrief:true, hasMdKoAudio:true, hasMdKoExplained:true, hasMdKo:true, hasMdEn:true};
T('fresh w/ brief -> brief', decide(FULL), 'AUDIO_BRIEF');
T('fresh, full audio only -> full', decide({...FULL, hasMdKoAudioBrief:false}), 'AUDIO_FULL');
T('audioFull switch -> full', decide({...FULL, audioFull:true}), 'AUDIO_FULL');
T('no audio at all -> explained', decide({hasMdKoExplained:true, hasMdKo:true}), 'EXPLAINED');
T('lang=en + brief -> orig en (no force ko)', decide({...FULL, langPref:'en'}), 'ORIG(en)');
T('explicit audio on -> brief (default sub-mode)', decide({...FULL, audioPref:'true'}), 'AUDIO_BRIEF');
T('brief-only fresh -> brief', decide({hasMdKoAudioBrief:true, hasMdKo:true}), 'AUDIO_BRIEF');
T('brief-only + audioFull -> still brief (no full to switch)', decide({hasMdKoAudioBrief:true, hasMdKo:true, audioFull:true}), 'AUDIO_BRIEF');
T('brief-only + explicit audioPref=true (restore) -> brief', decide({hasMdKoAudioBrief:true, hasMdKo:true, audioPref:'true'}), 'AUDIO_BRIEF');
console.log(process.exitCode ? 'FAIL' : 'ALL PASS');
