/// Wrapper for IKFast solver to provide a C interface for Python bindings
/// This creates a shared library that can be called from Python via ctypes

#define IKFAST_NO_MAIN

// Include the IKFast solver directly (same way MoveIt does it)
#include "episode1_urdf_1113_episode_arm_ikfast_solver.cpp"

#include <cstring>
#include <vector>
#include <cmath>

// C interface wrapper functions
// The IKFast functions are now available from the included solver file
extern "C" {

    /// Get number of joints
    int ikfast_get_num_joints() {
        return GetNumJoints();
    }

    /// Compute forward kinematics
    /// joints: array of 6 joint angles (radians)
    /// eetrans: output array of 3 elements for end-effector position (x, y, z)
    /// eerot: output array of 9 elements for end-effector rotation matrix (3x3, row-major)
    void ikfast_compute_fk(const double* joints, double* eetrans, double* eerot) {
        ComputeFk(joints, eetrans, eerot);
    }

    /// Compute inverse kinematics
    /// eetrans: array of 3 elements for end-effector position (x, y, z)
    /// eerot: array of 9 elements for end-effector rotation matrix (3x3, row-major)
    /// solutions_out: output array to store all solutions (max 8 solutions * 6 joints each = 48 doubles)
    /// num_solutions: output pointer to store the number of solutions found
    /// Returns: 1 if solutions found, 0 if no solution
    int ikfast_compute_ik(const double* eetrans, const double* eerot, double* solutions_out, int* num_solutions) {
        try {
            // Use the same pattern as MoveIt: IkSolutionList from ikfast namespace
            ikfast::IkSolutionList<IkReal> solutions;

            // Call ComputeIk
            bool success = ComputeIk(eetrans, eerot, nullptr, solutions);

            if (!success || solutions.GetNumSolutions() == 0) {
                *num_solutions = 0;
                return 0;
            }

            size_t num_sols = solutions.GetNumSolutions();
            *num_solutions = (int)num_sols;

            // Extract all solutions (same pattern as MoveIt's getSolution)
            int num_joints = GetNumJoints();

            for (size_t i = 0; i < num_sols; i++) {
                const ikfast::IkSolutionBase<IkReal>& sol = solutions.GetSolution(i);

                std::vector<IkReal> vsol(num_joints);

                // Handle free parameters properly (like MoveIt does)
                // This is critical - some solutions have free parameters that must be allocated
                std::vector<IkReal> vsolfree(sol.GetFree().size());

                sol.GetSolution(&vsol[0], vsolfree.size() > 0 ? &vsolfree[0] : nullptr);

                // Copy to output array
                for (int j = 0; j < num_joints; j++) {
                    solutions_out[i * num_joints + j] = vsol[j];
                }
            }

            return 1;
        } catch (const std::exception& e) {
            // Handle any exceptions gracefully
            *num_solutions = 0;
            return 0;
        }
    }

    /// Helper function to convert rotation matrix to quaternion
    /// rot: input rotation matrix (9 elements, 3x3 row-major)
    /// quat: output quaternion [w, x, y, z]
    void ikfast_rot_to_quat(const double* rot, double* quat) {
        double trace = rot[0] + rot[4] + rot[8];

        if (trace > 0.0) {
            double s = 0.5 / sqrt(trace + 1.0);
            quat[0] = 0.25 / s;  // w
            quat[1] = (rot[7] - rot[5]) * s;  // x
            quat[2] = (rot[2] - rot[6]) * s;  // y
            quat[3] = (rot[3] - rot[1]) * s;  // z
        } else if (rot[0] > rot[4] && rot[0] > rot[8]) {
            double s = 2.0 * sqrt(1.0 + rot[0] - rot[4] - rot[8]);
            quat[0] = (rot[7] - rot[5]) / s;  // w
            quat[1] = 0.25 * s;  // x
            quat[2] = (rot[1] + rot[3]) / s;  // y
            quat[3] = (rot[2] + rot[6]) / s;  // z
        } else if (rot[4] > rot[8]) {
            double s = 2.0 * sqrt(1.0 + rot[4] - rot[0] - rot[8]);
            quat[0] = (rot[2] - rot[6]) / s;  // w
            quat[1] = (rot[1] + rot[3]) / s;  // x
            quat[2] = 0.25 * s;  // y
            quat[3] = (rot[5] + rot[7]) / s;  // z
        } else {
            double s = 2.0 * sqrt(1.0 + rot[8] - rot[0] - rot[4]);
            quat[0] = (rot[3] - rot[1]) / s;  // w
            quat[1] = (rot[2] + rot[6]) / s;  // x
            quat[2] = (rot[5] + rot[7]) / s;  // y
            quat[3] = 0.25 * s;  // z
        }
    }

    /// Helper function to convert quaternion to rotation matrix
    /// quat: input quaternion [w, x, y, z]
    /// rot: output rotation matrix (9 elements, 3x3 row-major)
    void ikfast_quat_to_rot(const double* quat, double* rot) {
        double w = quat[0], x = quat[1], y = quat[2], z = quat[3];
        double x2 = x * x, y2 = y * y, z2 = z * z;
        double xy = x * y, xz = x * z, yz = y * z;
        double wx = w * x, wy = w * y, wz = w * z;

        rot[0] = 1.0 - 2.0 * (y2 + z2);
        rot[1] = 2.0 * (xy - wz);
        rot[2] = 2.0 * (xz + wy);
        rot[3] = 2.0 * (xy + wz);
        rot[4] = 1.0 - 2.0 * (x2 + z2);
        rot[5] = 2.0 * (yz - wx);
        rot[6] = 2.0 * (xz - wy);
        rot[7] = 2.0 * (yz + wx);
        rot[8] = 1.0 - 2.0 * (x2 + y2);
    }
}
