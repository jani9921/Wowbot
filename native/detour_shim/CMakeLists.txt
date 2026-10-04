cmake_minimum_required(VERSION 3.20)
project(aipc_detour CXX)

# Static MSVC runtime: the DLL runs on a fresh PC without VC++ redistributables.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

set(RECAST ${CMAKE_CURRENT_SOURCE_DIR}/../recastnavigation)
add_library(aipc_detour SHARED
    aipc_detour.cpp
    ${RECAST}/Detour/Source/DetourAlloc.cpp
    ${RECAST}/Detour/Source/DetourAssert.cpp
    ${RECAST}/Detour/Source/DetourCommon.cpp
    ${RECAST}/Detour/Source/DetourNavMesh.cpp
    ${RECAST}/Detour/Source/DetourNavMeshQuery.cpp
    ${RECAST}/Detour/Source/DetourNode.cpp)
target_include_directories(aipc_detour PRIVATE ${RECAST}/Detour/Include)
# TrinityCore mmaps use 64-bit polygon references (16-byte dtLink records).
target_compile_definitions(aipc_detour PRIVATE DT_POLYREF64=1)
set_target_properties(aipc_detour PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY_RELEASE ${CMAKE_CURRENT_SOURCE_DIR}/../bin)
