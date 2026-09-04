import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      redirect: '/zones',
    },
    {
      path: '/zones',
      name: 'ZoneList',
      component: () => import('@/views/ZoneList.vue'),
    },
    {
      path: '/zones/:zoneName/records',
      name: 'RecordList',
      component: () => import('@/views/RecordList.vue'),
    },
    {
      path: '/named-config',
      name: 'NamedConfig',
      component: () => import('@/views/NamedConfig.vue'),
    },
    {
      path: '/audit',
      name: 'Audit',
      component: () => import('@/views/Audit.vue'),
    },
    {
      path: '/change-requests',
      name: 'ChangeRequests',
      component: () => import('@/views/ChangeRequests.vue'),
    },
    {
      path: '/users',
      name: 'UserManagement',
      component: () => import('@/views/UserManagement.vue'),
    },
    {
      path: '/devices',
      name: 'DeviceManagement',
      component: () => import('@/views/DeviceManagement.vue'),
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  if (to.meta.public) {
    return next()
  }
  if (!authStore.isAuthenticated) {
    return next('/login')
  }
  return next()
})

export default router
