import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/api'

interface User {
  id: number
  username: string
  display_name: string | null
  email: string | null
  role: string
  is_active: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<User | null>(null)

  const isAuthenticated = computed(() => !!token.value)

  function setToken(t: string) {
    token.value = t
    localStorage.setItem('token', t)
  }

  function setUser(u: User) {
    user.value = u
  }

  async function login(username: string, password: string) {
    const { data } = await api.post('/auth/login', { username, password })
    setToken(data.access_token)
    // Fetch user profile after login
    await fetchMe()
    return data
  }

  async function tryRestoreSession() {
    if (!token.value) return
    await fetchMe()
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
  }

  async function fetchMe() {
    try {
      const { data } = await api.get('/auth/me')
      setUser(data)
    } catch {
      logout()
    }
  }

  return { token, user, isAuthenticated, login, logout, fetchMe, tryRestoreSession, setToken, setUser }
})
