import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { theme } from '@/src/theme';
import { View, StyleSheet } from 'react-native';

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.color.brand,
        tabBarInactiveTintColor: theme.color.textDim,
        tabBarStyle: {
          backgroundColor: theme.color.surface2,
          borderTopColor: theme.color.border,
          borderTopWidth: 1,
          height: 80, paddingBottom: 16, paddingTop: 8,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
      }}
    >
      <Tabs.Screen name="index" options={{
        title: 'TIMELINE',
        tabBarIcon: ({ color, focused }) => (
          <Ionicons name={focused ? 'time' : 'time-outline'} size={26} color={color} />
        ),
      }} />
      <Tabs.Screen name="ops" options={{
        title: 'OPS',
        tabBarIcon: ({ color, focused }) => (
          <Ionicons name={focused ? 'list-circle' : 'list-circle-outline'} size={28} color={color} />
        ),
      }} />
      <Tabs.Screen name="capture" options={{
        title: 'CAPTURE',
        tabBarIcon: ({ focused }) => (
          <View style={[styles.capWrap, focused && styles.capWrapActive]}>
            <Ionicons name="mic" size={30} color={focused ? theme.color.onBrand : theme.color.text} />
          </View>
        ),
      }} />
      <Tabs.Screen name="profile" options={{
        title: 'PROFILE',
        tabBarIcon: ({ color, focused }) => (
          <Ionicons name={focused ? 'person' : 'person-outline'} size={26} color={color} />
        ),
      }} />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  capWrap: {
    width: 56, height: 56, borderRadius: 28, backgroundColor: theme.color.surface3,
    alignItems: 'center', justifyContent: 'center', marginTop: -16,
    borderWidth: 2, borderColor: theme.color.border,
  },
  capWrapActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
});
