CREATE TABLE IF NOT EXISTS stt_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  name TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (
    provider IN (
      'groq',
      'whisper',
      'faster-whisper',
      'sensevoice',
      'sensevoice-local'
    )
  ),
  model_name TEXT,
  base_url TEXT,
  api_key_encrypted TEXT,
  language TEXT,
  device TEXT,
  compute_type TEXT,
  use_gpu BOOLEAN,
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_stt_profiles_user_name
  ON stt_profiles(user_id, name);

CREATE UNIQUE INDEX IF NOT EXISTS idx_stt_profiles_single_default
  ON stt_profiles(user_id)
  WHERE is_default = TRUE;

CREATE INDEX IF NOT EXISTS idx_stt_profiles_user_active
  ON stt_profiles(user_id, is_active);

ALTER TABLE stt_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own stt profiles" ON stt_profiles;
CREATE POLICY "Users can manage their own stt profiles" ON stt_profiles
  FOR ALL USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
